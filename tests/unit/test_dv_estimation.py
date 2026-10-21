"""The ΔV estimator must measure burns, not the gap between element sets.

Every test here is a regression guard on a measured failure. The estimator this
replaced reported 13.3 m/s for two fits of the same orbit differing by 1.6
seconds of along-track timing, and 1,971 m/s for a real 6.95 m/s burn seen
across a one-day gap. On a 3,676-element-set LEO catalogue it reported 3,304
manoeuvres and 166,666 m/s of cumulative ΔV against six real burns totalling
29.9 m/s.

The synthetic element sets below are built the way SGP4 itself drifts an orbit,
using the secular rates off its own initialised ``Satrec``. Building them with
closed-form J2 rates instead puts several degrees of phantom node and mean
anomaly drift into the pair, which the estimators then faithfully report: the
harness has to be right before the assertions mean anything.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from sgp4.api import Satrec

from spectre.astro.constants import MU_EARTH
from spectre.astro.dv_estimation import (
    build_breakdown,
    calibrate_noise,
    estimate_dv_epoch_swept,
    estimate_dv_mean_elements,
    secular_rates_deg_day,
    snapshot_from_record,
)
from spectre.astro.pattern_of_life import (
    TLERecord,
    _build_pairs,
    _estimate_dv,
    _merge_duplicate_detections,
    _satrec_to_record,
    analyse_pattern_of_life,
)

# ── Synthetic element set construction ────────────────────────────────────────

#: A 550 km, 53° LEO orbit. Orbital speed ≈ 7.59 km/s, which is what makes the
#: phase sensitivity so brutal: one degree of mean anomaly is 133 m/s of
#: apparent velocity difference.
_N0, _E0, _I0, _RA0, _AP0, _MA0, _EP0 = 15.1, 0.00015, 53.0, 120.0, 90.0, 45.0, 25300.0
_A0 = (MU_EARTH / ((_N0 * 2 * math.pi / 86400.0) ** 2)) ** (1 / 3)
_V0 = math.sqrt(MU_EARTH / _A0)


def _checksum(line: str) -> int:
    return sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line) % 10


def _tle(n: float, e: float, i: float, raan: float, argp: float,
         ma: float, epoch: float) -> str:
    """A well-formed two-line element set from mean elements."""
    l1 = f"1 62902U 25001A   {epoch:14.8f}  .00000000  00000-0  00000-0 0  999"
    l1 += str(_checksum(l1))
    l2 = (f"2 62902 {i % 360:8.4f} {raan % 360:8.4f} {f'{abs(e):.7f}'[2:9]} "
          f"{argp % 360:8.4f} {ma % 360:8.4f} {n:11.8f}    1")
    l2 += str(_checksum(l2))
    return f"{l1}\n{l2}"


def _base() -> str:
    return _tle(_N0, _E0, _I0, _RA0, _AP0, _MA0, _EP0)


def _sgp4_rates(tle: str) -> tuple[float, float, float]:
    """SGP4's own secular node, perigee and mean-anomaly rates, in °/day."""
    s = Satrec.twoline2rv(*tle.splitlines())
    return (math.degrees(s.nodedot) * 1440.0,
            math.degrees(s.argpdot) * 1440.0,
            math.degrees(s.mdot) * 1440.0)


def _coast(tle: str, days: float) -> str:
    """Advance an element set by *days* of natural drift. No manoeuvre."""
    s = Satrec.twoline2rv(*tle.splitlines())
    nd, ad, md = _sgp4_rates(tle)
    epoch = float(tle.splitlines()[0][18:32])
    return _tle(s.no_kozai * 1440.0 / (2 * math.pi), s.ecco, math.degrees(s.inclo),
                math.degrees(s.nodeo) + nd * days,
                math.degrees(s.argpo) + ad * days,
                math.degrees(s.mo) + md * days,
                epoch + days)


def _burn(tle: str, d_alt_km: float = 0.0, d_inc_deg: float = 0.0,
          d_ecc: float = 0.0) -> str:
    """Apply an impulse to an element set, at its own epoch."""
    s = Satrec.twoline2rv(*tle.splitlines())
    a = (MU_EARTH / ((s.no_kozai / 60.0) ** 2)) ** (1 / 3) + d_alt_km
    return _tle(math.sqrt(MU_EARTH / a ** 3) * 86400.0 / (2 * math.pi),
                s.ecco + d_ecc, math.degrees(s.inclo) + d_inc_deg,
                math.degrees(s.nodeo), math.degrees(s.argpo), math.degrees(s.mo),
                float(tle.splitlines()[0][18:32]))


def _pair(gap_days: float, burn_frac: float = 0.0, *, d_alt: float = 0.0,
          d_inc: float = 0.0, d_ecc: float = 0.0) -> tuple[TLERecord, TLERecord, float]:
    """Before and after records bracketing one impulse, plus its true ΔV."""
    before = _base()
    at_burn = _coast(before, gap_days * burn_frac) if burn_frac > 0 else before
    after = _burn(at_burn, d_alt, d_inc, d_ecc)
    if burn_frac < 1.0:
        after = _coast(after, gap_days * (1.0 - burn_frac))
    true_dv = math.sqrt(
        (0.5 * _V0 * (d_alt / _A0)) ** 2
        + (2 * _V0 * math.sin(math.radians(d_inc) / 2)) ** 2
        + (_V0 * d_ecc) ** 2
    ) * 1000.0
    return _satrec_to_record(before), _satrec_to_record(after), true_dv


def _rec(tle: str, *, source: str = "", data_mode: str = "") -> TLERecord:
    r = _satrec_to_record(tle)
    r.source, r.data_mode = source, data_mode
    return r


# ── Phase immunity: the defect that made the old figures meaningless ─────────

class TestPhaseIsNotDeltaV:
    """Along-track phase carries no ΔV. Reading it as ΔV was the whole bug."""

    @pytest.mark.parametrize(
        ("phase_deg", "old_method_reported_m_s"),
        [(0.001, 0.13), (0.01, 1.33), (0.1, 13.27), (1.0, 132.7), (5.0, 663.4), (30.0, 3936.1)],
    )
    def test_same_orbit_differing_only_in_mean_anomaly_has_no_delta_v(
        self, phase_deg: float, old_method_reported_m_s: float
    ) -> None:
        """Two fits of one orbit at one epoch, differing only in phase.

        True ΔV is zero in every case. The second parameter records what the
        propagation-difference method reported, so the regression is visible:
        a tenth of a degree is 1.6 seconds of along-track timing and it read as
        13 m/s of manoeuvre.
        """
        before = _satrec_to_record(_base())
        after = _satrec_to_record(
            _tle(_N0, _E0, _I0, _RA0, _AP0, _MA0 + phase_deg, _EP0)
        )
        assert _estimate_dv(before, after) * 1000.0 < 0.01, (
            f"{phase_deg}° of phase must not register as ΔV; the old method "
            f"reported {old_method_reported_m_s} m/s here"
        )

    def test_mean_anomaly_is_never_read(self) -> None:
        """The element estimator must not touch phase at all."""
        b = snapshot_from_record(_satrec_to_record(_base()))
        for ma in (0.0, 90.0, 180.0, 270.0, 359.9):
            a = snapshot_from_record(
                _satrec_to_record(_tle(_N0, _E0, _I0, _RA0, _AP0, ma, _EP0))
            )
            assert estimate_dv_mean_elements(b, a, 0.0).dv_km_s == pytest.approx(0.0, abs=1e-12)

    def test_natural_drift_over_fifteen_days_is_not_a_manoeuvre(self) -> None:
        """68° of natural node precession must read as zero ΔV."""
        before, after, true_dv = _pair(15.0)
        assert true_dv == 0.0
        bd = build_breakdown(before, after, 15.0)
        assert bd.dv_m_s < 0.1
        assert bd.elements.dv_m_s < 0.1


# ── Accuracy against known burns ─────────────────────────────────────────────

class TestKnownBurns:
    @pytest.mark.parametrize("d_alt", [1.0, 12.66, 25.0])
    @pytest.mark.parametrize("gap", [0.2, 1.0, 5.0, 15.0])
    def test_tangential_burn_is_gap_independent(self, d_alt: float, gap: float) -> None:
        """The same burn must read the same whatever the catalogue cadence.

        The old method's answer scaled with the gap: a 6.95 m/s burn read as
        395 m/s at 0.2 days and 1,971 m/s at one day.
        """
        before, after, true_dv = _pair(gap, 0.0, d_alt=d_alt)
        bd = build_breakdown(before, after, gap)
        assert bd.dv_m_s == pytest.approx(true_dv, rel=0.02)
        assert bd.elements.dv_m_s == pytest.approx(true_dv, rel=0.02)

    @pytest.mark.parametrize("d_inc", [0.01, 0.1, 1.0, 5.0])
    def test_plane_change_matches_the_analytic_relation(self, d_inc: float) -> None:
        """Δv = 2·v·sin(Δi/2), with natural precession removed first."""
        before, after, true_dv = _pair(1.0, 0.5, d_inc=d_inc)
        bd = build_breakdown(before, after, 1.0)
        assert bd.dv_m_s == pytest.approx(true_dv, rel=0.02)

    @pytest.mark.parametrize("d_ecc", [1e-5, 1e-4, 1e-3])
    def test_eccentricity_burn_lands_in_the_radial_channel(self, d_ecc: float) -> None:
        before, after, true_dv = _pair(1.0, 0.5, d_ecc=d_ecc)
        bd = build_breakdown(before, after, 1.0)
        assert bd.dv_m_s == pytest.approx(true_dv, rel=0.05)
        radial = next(c for c in bd.components if c.channel == "radial")
        assert radial.dv_km_s * 1000.0 == pytest.approx(true_dv, rel=0.05)

    def test_combined_burn_decomposes_into_its_channels(self) -> None:
        """Each channel carries its own term and the total is their RSS."""
        before, after, true_dv = _pair(3.0, 0.3, d_alt=12.66, d_inc=0.1)
        bd = build_breakdown(before, after, 3.0)
        by_channel = {c.channel: c.dv_km_s * 1000.0 for c in bd.components}
        assert by_channel["along_track"] == pytest.approx(6.95, rel=0.02)
        assert by_channel["cross_track"] == pytest.approx(13.25, rel=0.02)
        assert bd.elements.dv_m_s == pytest.approx(true_dv, rel=0.02)
        assert bd.dv_m_s == pytest.approx(true_dv, rel=0.02)

    def test_every_component_carries_the_numbers_that_produced_it(self) -> None:
        """The operator must be able to recompute each term by hand."""
        before, after, _ = _pair(1.0, 0.0, d_alt=12.66)
        bd = build_breakdown(before, after, 1.0)
        along = next(c for c in bd.components if c.channel == "along_track")
        assert along.formula == "Δv = n · Δa / 2"
        n = along.inputs["n_rad_s"]
        d_a = along.inputs["delta_a_km"]
        assert abs(n * d_a / 2.0) == pytest.approx(along.dv_km_s, rel=1e-9)
        assert along.inputs["a_after_km"] - along.inputs["a_before_km"] == pytest.approx(d_a)

    def test_the_burn_is_dated_not_assumed(self) -> None:
        """The after-epoch can be wrong by the whole gap; the burn time is measured."""
        before, after, _ = _pair(4.0, 0.25, d_alt=25.0)
        bd = build_breakdown(before, after, 4.0)
        assert bd.burn_epoch is not None
        frac = (bd.burn_epoch - before.epoch).total_seconds() / 86400.0 / 4.0
        assert frac == pytest.approx(0.25, abs=0.05)
        assert bd.burn_epoch < after.epoch - timedelta(days=2)


# ── Secular rates ────────────────────────────────────────────────────────────

class TestSecularRates:
    def test_rates_come_from_sgp4_and_are_degrees_per_day(self) -> None:
        raan_rate, argp_rate = secular_rates_deg_day(_base(), _A0, _E0, _I0)
        s = Satrec.twoline2rv(*_base().splitlines())
        assert raan_rate == pytest.approx(math.degrees(s.nodedot) * 1440.0)
        assert argp_rate == pytest.approx(math.degrees(s.argpdot) * 1440.0)
        # A 53° prograde LEO orbit regresses its node a few degrees a day.
        assert -8.0 < raan_rate < -2.0

    def test_unparseable_element_set_falls_back_to_the_closed_form(self) -> None:
        raan_rate, argp_rate = secular_rates_deg_day("not a tle", _A0, _E0, _I0)
        assert raan_rate < 0.0
        assert math.isfinite(argp_rate)


# ── Noise calibration ────────────────────────────────────────────────────────

class TestNoiseCalibration:
    def test_floor_is_median_plus_five_mads(self) -> None:
        samples = [0.001] * 50 + [0.003] * 50
        noise = calibrate_noise(samples)
        assert noise.median_km_s == pytest.approx(0.002)
        assert noise.mad_km_s == pytest.approx(0.001)
        assert noise.floor_km_s == pytest.approx(0.007)
        assert noise.samples == 100

    def test_real_burns_cannot_inflate_the_threshold_meant_to_find_them(self) -> None:
        """A minority of enormous samples must not move median or MAD."""
        quiet = [0.001 + (i % 7) * 0.0001 for i in range(1000)]
        loud = quiet[:-10] + [5.0] * 10          # 1% of pairs are huge burns
        assert calibrate_noise(loud).floor_km_s == pytest.approx(
            calibrate_noise(quiet).floor_km_s, rel=0.01
        )

    def test_too_few_samples_falls_back_to_the_absolute_floor(self) -> None:
        noise = calibrate_noise([0.5, 0.6])
        assert noise.floor_km_s == pytest.approx(1.0e-4)
        assert "insufficient" in noise.method

    def test_identical_samples_give_no_signal_to_noise(self) -> None:
        """MAD of zero must not divide by zero."""
        noise = calibrate_noise([0.002] * 100)
        assert noise.mad_km_s == 0.0
        assert noise.snr(0.5) is None
        assert noise.floor_km_s == pytest.approx(0.002)


# ── Provenance and pairing ───────────────────────────────────────────────────

class TestSourceMatching:
    def test_fits_from_different_providers_are_not_differenced(self) -> None:
        """One organisation's orbit determination against another's is not a burn."""
        recs = []
        for k in range(6):
            tle = _coast(_base(), k * 0.1)
            recs.append(_rec(tle, source="18SDS" if k % 2 == 0 else "COMSPOC"))
        pairs = _build_pairs(recs)
        assert pairs, "source-matched pairing must still produce pairs"
        for before, after, _ in pairs:
            assert before.source == after.source

    def test_unattributed_catalogues_fall_back_to_consecutive_pairing(self) -> None:
        recs = [_satrec_to_record(_coast(_base(), k * 0.1)) for k in range(5)]
        assert len(_build_pairs(recs)) == 4

    def test_a_single_source_also_pairs_consecutively(self) -> None:
        recs = [_rec(_coast(_base(), k * 0.1), source="18SDS") for k in range(5)]
        assert len(_build_pairs(recs)) == 4

    def test_a_cross_source_pair_is_flagged_and_cannot_be_confirmed(self) -> None:
        before, after, _ = _pair(0.1, 0.0, d_alt=12.66)
        before.source, after.source = "18SDS", "COMSPOC"
        noise = calibrate_noise([1e-5] * 100)
        bd = build_breakdown(before, after, 0.1, noise)
        assert bd.cross_source
        assert any("different sources" in w for w in bd.warnings)
        assert bd.confidence != "HIGH"


# ── Confidence grading ───────────────────────────────────────────────────────

class TestConfidence:
    def test_a_clean_burn_well_above_noise_is_confirmed(self) -> None:
        before, after, _ = _pair(0.5, 0.3, d_alt=25.0)
        noise = calibrate_noise([1e-5 + (i % 5) * 1e-6 for i in range(500)])
        assert build_breakdown(before, after, 0.5, noise).confidence == "HIGH"

    def test_a_figure_below_the_measured_floor_is_rejected(self) -> None:
        before, after, _ = _pair(0.5, 0.0, d_alt=0.05)
        noise = calibrate_noise([0.01] * 100)          # floor 10 m/s
        bd = build_breakdown(before, after, 0.5, noise)
        assert bd.confidence == "REJECT"
        assert not bd.believable

    def test_a_non_positive_gap_cannot_be_confirmed(self) -> None:
        """Two effectively simultaneous fits cannot bracket a manoeuvre."""
        before = _satrec_to_record(_base())
        after = _burn(_base(), d_alt_km=25.0)
        bd = build_breakdown(before, _satrec_to_record(after), 0.0)
        assert any("Non-positive epoch gap" in w for w in bd.warnings)
        assert bd.confidence != "HIGH"


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_a_malformed_element_set_fails_loudly_not_silently(self) -> None:
        before, after, _ = _pair(1.0, 0.0, d_alt=12.66)
        after.tle = "garbage"
        bd = build_breakdown(before, after, 1.0)
        assert bd.swept.failed
        assert bd.headline_method == "mean_element"
        assert any("Epoch-swept estimator unavailable" in w for w in bd.warnings)
        assert bd.dv_m_s == pytest.approx(6.95, rel=0.05)

    def test_zero_gap_does_not_divide_by_zero(self) -> None:
        before = _satrec_to_record(_base())
        est = estimate_dv_epoch_swept(_base(), _base(), before.epoch, before.epoch)
        assert not est.failed
        assert est.dv_km_s == pytest.approx(0.0, abs=1e-9)

    def test_merging_an_empty_or_single_detection_list_is_a_no_op(self) -> None:
        assert _merge_duplicate_detections([], 1.0) == ([], 0)

    def test_identical_element_sets_report_no_manoeuvre(self) -> None:
        r = _satrec_to_record(_base())
        assert _estimate_dv(r, r) == pytest.approx(0.0, abs=1e-12)


# ── Two-tier reporting ───────────────────────────────────────────────────────

class TestTwoTierReporting:
    @staticmethod
    def _catalogue(n: int = 300, burn_at: int | tuple[int, ...] = 150,
                   d_alt_km: float = 25.0) -> list[TLERecord]:
        """A coasting object with unmistakable burns partway through."""
        burns = (burn_at,) if isinstance(burn_at, int) else burn_at
        recs, tle = [], _base()
        for k in range(n):
            if k in burns:
                tle = _burn(tle, d_alt_km=d_alt_km)
            recs.append(_rec(tle, source="18SDS"))
            tle = _coast(tle, 0.25)
        return recs

    def test_only_confirmed_events_carry_the_headline_statistics(self) -> None:
        pol = analyse_pattern_of_life(self._catalogue(), satno=62902, name="TEST")
        assert all(m.confidence == "HIGH" for m in pol.manoeuvres)
        assert all(m.confidence != "HIGH" for m in pol.candidate_manoeuvres)
        confirmed_total = sum(m.delta_v_km_s for m in pol.manoeuvres)
        # total_dv_km_s is rounded to 4 decimal places on the way out, which is
        # 0.1 m/s of granularity on the cumulative figure.
        assert pol.total_dv_km_s == pytest.approx(confirmed_total, abs=1e-4)
        candidate_total = sum(m.delta_v_km_s for m in pol.candidate_manoeuvres)
        if candidate_total:
            assert pol.total_dv_km_s < confirmed_total + candidate_total

    def test_the_detection_audit_accounts_for_every_pair(self) -> None:
        pol = analyse_pattern_of_life(self._catalogue(), satno=62902, name="TEST")
        assert pol.pairs_examined > 0
        assert pol.noise_model is not None
        assert pol.noise_model.samples == pol.pairs_examined
        assert pol.rejected_below_floor >= 0
        assert (pol.rejected_below_floor
                + len(pol.manoeuvres) + len(pol.candidate_manoeuvres)
                + pol.rejected_on_evidence + pol.merged_duplicates) <= pol.pairs_examined

    def test_a_quiet_object_does_not_manufacture_a_propellant_budget(self) -> None:
        """300 coasting element sets, no burn, must not consume propellant.

        The catalogue this replaces reported 36,686 m/s of cumulative ΔV and
        100% propellant consumed for a LEO smallsat whose entire realistic
        lifetime budget is 500 to 2,500 m/s.
        """
        recs, tle = [], _base()
        for _ in range(300):
            recs.append(_rec(tle, source="18SDS"))
            tle = _coast(tle, 0.25)
        from spectre.domain.pol_assessment import assess_pattern_of_life

        pol = analyse_pattern_of_life(recs, satno=62902, name="QUIET")
        assert pol.manoeuvres == []
        assert pol.total_dv_km_s == pytest.approx(0.0, abs=1e-9)
        assert assess_pattern_of_life(pol).propellant.propellant_used_pct < 0.1

    def test_a_real_burn_is_found_and_sized_correctly(self) -> None:
        pol = analyse_pattern_of_life(self._catalogue(), satno=62902, name="TEST")
        assert len(pol.manoeuvres) == 1
        found = pol.manoeuvres[0]
        assert found.delta_v_km_s * 1000.0 == pytest.approx(13.73, rel=0.05)
        assert found.breakdown is not None
        assert found.breakdown.confidence == "HIGH"


# ── Unit discipline ──────────────────────────────────────────────────────────

class TestUnitDiscipline:
    """The astro package works in km and km/s. Conversion happens once, elsewhere."""

    def test_every_metres_per_second_property_is_a_pure_thousandfold(self) -> None:
        before, after, _ = _pair(1.0, 0.0, d_alt=12.66)
        noise = calibrate_noise([1e-5 + (i % 5) * 1e-6 for i in range(200)])
        bd = build_breakdown(before, after, 1.0, noise)
        assert bd.dv_m_s == pytest.approx(bd.dv_km_s * 1000.0)
        for est in bd.estimates:
            assert est.dv_m_s == pytest.approx(est.dv_km_s * 1000.0)
        for c in bd.components:
            assert c.dv_m_s == pytest.approx(c.dv_km_s * 1000.0)
        assert bd.noise is not None
        assert bd.noise.floor_m_s == pytest.approx(bd.noise.floor_km_s * 1000.0)
        assert bd.noise.median_m_s == pytest.approx(bd.noise.median_km_s * 1000.0)
        assert bd.noise.mad_m_s == pytest.approx(bd.noise.mad_km_s * 1000.0)

    def test_delta_v_figures_are_kilometres_per_second_sized(self) -> None:
        """A 13 m/s burn must be 0.013 in the astro layer, not 13."""
        before, after, _ = _pair(1.0, 0.0, d_alt=25.0)
        bd = build_breakdown(before, after, 1.0)
        assert 0.005 < bd.dv_km_s < 0.05

    def test_component_input_keys_name_their_own_units(self) -> None:
        """An operator reading the drill-down must not have to guess."""
        before, after, _ = _pair(1.0, 0.0, d_alt=12.66, d_inc=0.05)
        bd = build_breakdown(before, after, 1.0)
        known = ("_km", "_deg", "_km_s", "_rad_s", "_deg_day")
        dimensionless = {"e_before", "e_after", "delta_e_vector",
                         "delta_e_explained", "delta_e_residual"}
        for c in bd.components:
            for key in c.inputs:
                assert key in dimensionless or key.endswith(known), (
                    f"{c.channel} input {key!r} does not name its unit"
                )


# ── The view contract ────────────────────────────────────────────────────────

class TestDrillDownContract:
    """A partial context is how a panel ships blank. Both branches must be full."""

    def test_the_view_returns_every_key_with_and_without_a_breakdown(self) -> None:
        from spectre.web.routes.pol import _breakdown_view

        before, after, _ = _pair(1.0, 0.0, d_alt=25.0)
        pol = analyse_pattern_of_life(
            TestTwoTierReporting._catalogue(), satno=62902, name="TEST",
        )
        m = pol.manoeuvres[0]
        full = _breakdown_view(m)
        assert full["has_breakdown"] is True

        m.breakdown = None
        bare = _breakdown_view(m)
        assert bare["has_breakdown"] is False
        assert set(bare) == set(full), (
            "the no-breakdown branch must define every name the template reads"
        )

    def test_the_panel_renders_in_both_branches_under_strict_undefined(self) -> None:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        from spectre.web.format_units import format_m_s, format_tof_label
        from spectre.web.routes.pol import _breakdown_view

        env = Environment(
            loader=FileSystemLoader("spectre/web/templates"),
            undefined=StrictUndefined, autoescape=True,
        )
        env.filters["m_s"] = format_m_s
        env.filters["tof"] = format_tof_label
        template = env.get_template("partials/pol_manoeuvre_detail.html")

        pol = analyse_pattern_of_life(
            TestTwoTierReporting._catalogue(), satno=62902, name="TEST",
        )
        m = pol.manoeuvres[0]
        html = template.render(m=m, satno=62902, confirmed=True, **_breakdown_view(m))
        for expected in ("Along-track", "Radial", "Cross-track", "Element sets",
                         "Estimators", "Detection floor"):
            assert expected in html

        m.breakdown = None
        assert template.render(m=m, satno=62902, confirmed=True, **_breakdown_view(m))
