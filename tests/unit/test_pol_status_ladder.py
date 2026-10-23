"""The operator-facing status ladder, and the three constants that set it.

Release 0.5.24 lifted the ladder out of ``analyse_pattern_of_life`` to clear
SonarQube's cognitive-complexity cap, and in doing so turned three thresholds
that had been inline literals into named constants. The review of that refactor
found no behaviour change and one real hole: the ANOMALOUS and CAUTION arms
were never executed by any test, so all three constants could be mistyped and
the suite would stay green. That was verified by mutation, not assumed.

These are the boundaries themselves, every comparison exclusive, so a typo in
any of the three moves a test rather than moving an operator's threat reading
silently.
"""


from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.pattern_of_life import (
    Manoeuvre,
    PolStats,
    TLERecord,
    _pol_status_and_reason,
)

_LEO_TLE_A = (
    "1 25544U 98067A   24001.00000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 25544  51.6400 100.0000 0001000  90.0000 270.0000 15.49000000 00001"
)


def _make_record(sma: float = 6778.0, ecc: float = 0.001, inc: float = 51.6) -> TLERecord:
    from spectre.astro.pattern_of_life import _parse_tle_epoch
    lines = _LEO_TLE_A.strip().split("\n")
    epoch = _parse_tle_epoch(lines[0])
    return TLERecord(
        epoch=epoch, tle=_LEO_TLE_A,
        sma_km=sma, ecc=ecc, inc_deg=inc,
        raan_deg=0.0, argp_deg=0.0, mean_anomaly_deg=0.0,
        mean_motion_revday=15.54, bstar=1.0e-4,
        alt_km=sma - 6371.0, period_min=92.0, regime="LEO",
    )


_BURN = datetime(2024, 1, 1, tzinfo=UTC)


def _manoeuvre(dv: float) -> Manoeuvre:
    rec = _make_record()
    return Manoeuvre(
        epoch=_BURN, gap_days=1.0, delta_v_km_s=dv,
        delta_alt_km=0.0, delta_inc_deg=0.0, delta_ecc=0.0,
        delta_raan_corrected_deg=0.0, delta_argp_corrected_deg=0.0,
        delta_period_s=0.0, delta_drift_deg_day=None,
        dominant_element="altitude", tle_before=rec, tle_after=rec,
    )


# mean 0 and std 1 make z numerically equal to the latest dV, so each case
# below names the sigma boundary it straddles.
_UNIT_STATS = PolStats(mean=0.0, std=1.0, p5=0.0, p95=0.0,
                       low_2sigma=0.0, high_2sigma=0.0, n=10)

_NORMAL_REASON = "All metrics within normal historical bounds."


class TestPolStatusLadder:
    @pytest.mark.parametrize(("z", "expected"), [
        (2.0,    "NORMAL"),     # _STATUS_CAUTION_SIGMA is exclusive
        (2.0001, "CAUTION"),
        (3.0,    "CAUTION"),    # _STATUS_ANOMALOUS_SIGMA is exclusive
        (3.0001, "ANOMALOUS"),
    ])
    def test_sigma_boundaries(self, z: float, expected: str) -> None:
        status, _ = _pol_status_and_reason(
            _BURN + timedelta(days=1.0), [_manoeuvre(z)], _UNIT_STATS,
        )
        assert status == expected

    @pytest.mark.parametrize(("age_days", "expected"), [
        (9.9,  "ANOMALOUS"),    # inside the recency window, ladder applies
        (10.0, "NORMAL"),       # _STATUS_RECENT_DAYS is exclusive
    ])
    def test_recency_boundary(self, age_days: float, expected: str) -> None:
        status, reason = _pol_status_and_reason(
            _BURN + timedelta(days=age_days), [_manoeuvre(4.0)], _UNIT_STATS,
        )
        assert status == expected
        if expected == "NORMAL":
            assert reason == _NORMAL_REASON
