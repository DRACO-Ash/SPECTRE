"""Figures the Decision Engine shows beside a cell's closest approach, each with what it rests on.

The time of closest approach's uncertainty (SPC-118): the element sets' position error at the TCA over the closing
speed, with all of the error taken along the approach, so it errs wide.

Our burn on the blue asset (SPC-121): what a manoeuvre response asks for (ResponseBurnSpec), and what its sized
burn buys (ResponseFigure), the closest approach after it against the one before it, each by RK45 for both orbits
or, in a sampled row, P5 after against P5 before, paired by sample.

Imports only the astro package and the standard library, so the domain never reaches the web layer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import NamedTuple

import numpy as np

from spectre.astro.response_burn import BurnAxis, SizedBurn

_SECONDS_PER_MINUTE = 60.0
_SECONDS_PER_HOUR = 3600.0
#: A closing speed below this, km/s, is rounding noise: the time cannot be fixed from it, and it is never divided by.
SLOWEST_CLOSING_KM_S = 1e-9
#: Below these sigmas the hours after the scenario epoch are printed to 2 and to 1 decimal; above, whole hours. Each
#: is where half the last digit (0.05 h, then 0.5 h) reaches the sigma, so rounding never moves the time by more than
#: its uncertainty: a 7 min sigma prints 2.4 h, not 2 h.
_TWO_DECIMALS_BELOW_S = 180.0
_ONE_DECIMAL_BELOW_S = 1800.0

#: The hover on a TCA with an uncertainty. The element-set model is spectre/astro/along_track.py's.
TCA_TITLE = (
    "TCA known to {pm}: element-set error of {pos:.1f} km at the TCA, both objects combined in quadrature (the "
    "sweep's 1 km at epoch plus 2 km a day in LEO, 2 km plus 1 km a day at GEO), over a closing speed of "
    "{v:,.1f} m/s. All of the error is taken along the approach, so it errs wide; our burn's execution error is not "
    "in it."
)
TCA_TOO_SLOW = (
    "TCA not known to better than the {span:.1f} h searched: the objects close at {v:.2f} m/s, too slowly to fix the "
    "time from a {pos:.1f} km position error."
)
#: The ± on a TCA too slow to fix: the time is not known to better than the span searched.
TCA_TOO_SLOW_PM = "± more than the {span:.1f} h searched"
TCA_AT_EDGE = "No TCA uncertainty: the smallest separation is at the edge of the search, not an encounter."
TCA_NO_SPEED = "No TCA uncertainty: this series recorded no closing speed for the sample that sets the TCA."


def sigma_text(sigma_s: float) -> str:
    """A TCA's uncertainty at its scale: under 1 s, whole seconds, whole minutes, then tenths of an hour."""
    if sigma_s < 1.0:
        return "± under 1 s"
    if sigma_s < _SECONDS_PER_MINUTE:
        return f"± {sigma_s:.0f} s"
    if sigma_s < _SECONDS_PER_HOUR:
        return f"± {sigma_s / _SECONDS_PER_MINUTE:.0f} min"
    return f"± {sigma_s / _SECONDS_PER_HOUR:.1f} h"


class TcaUncertainty(NamedTuple):
    """How closely a time of closest approach is known, s (1 sigma); None when it cannot be said, and why."""

    sigma_s: float | None
    position_error_km: float
    closing_speed_km_s: float     # NaN when the series recorded none
    span_s: float
    at_edge: bool

    @property
    def too_slow(self) -> bool:
        """Whether the TCA was found but the approach is too slow to fix its time within the span searched."""
        return self.sigma_s is None and not self.at_edge and not math.isnan(self.closing_speed_km_s)

    @property
    def pm(self) -> str:
        """The uncertainty at its scale (sigma_text); the span searched when too slow to fix; nothing at an edge or
        with no speed."""
        sigma = self.sigma_s
        if sigma is None:
            return TCA_TOO_SLOW_PM.format(span=self.span_s / _SECONDS_PER_HOUR) if self.too_slow else ""
        return sigma_text(sigma)

    def hours(self, h: float) -> str:
        """*h* hours after the scenario epoch to no finer than the uncertainty allows: whole hours when too slow to
        fix, 2 decimals at an edge, with no speed or for a cell built before SPC-118."""
        if self.too_slow:
            return f"{h:.0f}"
        sigma = self.sigma_s
        if sigma is None or sigma < _TWO_DECIMALS_BELOW_S:
            return f"{h:.2f}"
        return f"{h:.1f}" if sigma < _ONE_DECIMAL_BELOW_S else f"{h:.0f}"

    @property
    def title(self) -> str:
        """What the uncertainty rests on, or why there is none."""
        if self.at_edge:
            return TCA_AT_EDGE
        if math.isnan(self.closing_speed_km_s):
            return TCA_NO_SPEED
        if self.sigma_s is None:
            return TCA_TOO_SLOW.format(
                span=self.span_s / _SECONDS_PER_HOUR, v=self.closing_speed_km_s * 1000.0, pos=self.position_error_km,
            )
        return TCA_TITLE.format(pm=self.pm, pos=self.position_error_km, v=self.closing_speed_km_s * 1000.0)


# ── Our burn (SPC-121) ──

#: The budget a target separation is sized within unless the operator gives another, km/s (50 m/s).
DEFAULT_BUDGET_KM_S = 0.05
_M_S_PER_KM_S = 1000.0


@dataclass(frozen=True)
class ResponseBurnSpec:
    """What a manoeuvre response asks of our burn: the separation to reach, the delta-V budget and the axis."""

    target_km: float
    budget_km_s: float = DEFAULT_BUDGET_KM_S
    axis: BurnAxis = BurnAxis.CHEAPEST


#: Each axis's two senses as the operator reads them, positive first.
_SENSES: dict[BurnAxis, tuple[str, str]] = {
    BurnAxis.IN_TRACK: ("prograde", "retrograde"),
    BurnAxis.RADIAL: ("outward", "inward"),
    BurnAxis.CROSS_TRACK: ("positive normal", "negative normal"),
}

RESPONSE_LINE = (
    "Our burn: {dv:.2f} m/s {axis} ({sense}) at {at:%Y-%m-%d %H:%M} UTC, {h:.1f} h after the scenario epoch. It buys "
    "{buys:+.1f} km: {before:.1f} km at {tb:%H:%M} UTC before it, {after:.1f} km at {ta:%H:%M} UTC after it, both by "
    "RK45 for both orbits."
)
RESPONSE_NONE_NEEDED = (
    "No burn needed: the closest approach without one, {before:.1f} km, is already at or beyond the {target:g} km "
    "target, so this response spends nothing."
)
RESPONSE_SHORT = (
    "Our burn: the whole {budget:g} m/s budget, {axis} ({sense}) at {at:%Y-%m-%d %H:%M} UTC, reaches {after:.1f} km, "
    "short of the {target:g} km target."
)
RESPONSE_EDGE = (
    " The objects are still closing when the search ends, so the target holds only to {end:%Y-%m-%d %H:%M} UTC."
)
_SAMPLED_BUYS = " Across samples it buys {buys:+.1f} km at P5: {p5b:.1f} km before it, {p5a:.1f} km after it."
SAMPLED_RESPONSE_LINE = (
    "Our burn: {dv:.2f} m/s {axis} ({sense}) at {at:%Y-%m-%d %H:%M} UTC, sized on the hypothesis's nominal burn to "
    "put its closest approach at {target:g} km." + _SAMPLED_BUYS
)
#: SAMPLED_RESPONSE_LINE when the whole budget, flown against the hypothesis's nominal burn, falls short.
SAMPLED_RESPONSE_SHORT = (
    "Our burn: the whole {budget:g} m/s budget, {axis} ({sense}) at {at:%Y-%m-%d %H:%M} UTC, falls short of the "
    "{target:g} km target on the hypothesis's nominal burn, reaching {nominal:.1f} km." + _SAMPLED_BUYS
)
SAMPLED_UNDER_TARGET = (
    " P5 after our burn is {p5a:.1f} km, under the {target:g} km target: {share} samples still came closer than the "
    "target."
)
#: SAMPLED_UNDER_TARGET when the nominal needed no burn, so none was applied.
SAMPLED_NONE_UNDER_TARGET = (
    " P5 across samples is {p5a:.1f} km, under the {target:g} km target: {share} samples came closer than the target."
)
#: The share of samples under the target when the cell did not count them: P5 under it says only this much.
_AT_LEAST_ONE_IN_20 = "at least 1 in 20"
RESPONSE_DV_NOTE = (
    "our burn: {dv:.2f} m/s at {at:%Y-%m-%d %H:%M} UTC, the response's time to execute after the scenario epoch "
    "(entered); its axis {axis_basis}; its sense the one that opens the closest approach more when flown; its size "
    "{size}, searched by RK45 with J2 and exponential drag for both orbits, doubling from the manoeuvre library's "
    "size {search}"
)
_SIZE_REACHED = "the smallest found that puts the closest approach at {target:g} km or more within the {budget:g} m/s budget"
_SIZE_SHORT = "the whole {budget:g} m/s budget, since no burn within it was found to put the closest approach at {target:g} km"
_SEARCH_REACHED = "and halving to within 1 %, so a smaller burn on this axis may also reach the target"
_SEARCH_SHORT = "to the whole budget"
RESPONSE_NONE_NOTE = (
    "our burn: none, since the closest approach without one is already at or beyond the {target:g} km target, by RK45 "
    "with J2 and exponential drag for both orbits"
)
_LIBRARY_AXIS = "{axis}, the manoeuvre library's cheapest for a {lead:.1f} h lead (Clohessy-Wiltshire)"
_ENTERED_AXIS = "{axis}, entered by the operator"


@dataclass(frozen=True)
class ResponseFigure:
    """What one sized burn buys in one cell, with its time, target and budget.

    In a computed cell it buys the RK45 closest approach after the burn minus the one before it, from the same arcs.
    In a sampled cell, *sampled_before_p5_km* and *sampled_after_p5_km* are P5 of the samples before and after it,
    paired by sample, and it buys their difference; *sampled_under_target* counts the samples, after our burn or
    with none, that came closer than the target, of how many.
    """

    sized: SizedBurn
    burn_at_utc: datetime
    target_km: float
    budget_km_s: float
    sampled_before_p5_km: float | None = None
    sampled_after_p5_km: float | None = None
    sampled_under_target: tuple[int, int] | None = None

    @property
    def delta_v_km_s(self) -> float:
        """The burn's size, km/s; 0 when none was needed."""
        burn = self.sized.burn
        return 0.0 if burn is None else float(np.linalg.norm(burn.delta_v_ric_km_s))

    @property
    def buys_km(self) -> float:
        """The closest approach after our burn minus the one before it, km: P5 against P5 in a sampled cell."""
        if self.sampled_before_p5_km is not None and self.sampled_after_p5_km is not None:
            return self.sampled_after_p5_km - self.sampled_before_p5_km
        return self.sized.after.approach.miss_km - self.sized.before.approach.miss_km

    @property
    def _sense(self) -> str:
        positive, negative = _SENSES.get(self.sized.axis, ("positive", "negative"))
        return positive if self.sized.sense > 0 else negative

    @property
    def line(self) -> str:
        """The burn and what it buys, in the cell."""
        if self.sized.burn is None:
            return RESPONSE_NONE_NEEDED.format(before=self.sized.before.approach.miss_km, target=self.target_km) + (
                self._under_target()
            )
        if self.sampled_after_p5_km is not None:
            return self._sampled_line()
        if not self.sized.reached:
            return RESPONSE_SHORT.format(
                budget=self.budget_km_s * _M_S_PER_KM_S, axis=self.sized.axis.value, sense=self._sense,
                at=self.burn_at_utc, after=self.sized.after.approach.miss_km, target=self.target_km,
            ) + self._edge()
        before, after = self.sized.before, self.sized.after
        return RESPONSE_LINE.format(
            dv=self.delta_v_km_s * _M_S_PER_KM_S, axis=self.sized.axis.value, sense=self._sense, at=self.burn_at_utc,
            h=self.sized.burn.at_s / 3600.0, buys=self.buys_km, before=before.approach.miss_km,
            tb=before.approach.tca_utc(before.window.start_utc), after=after.approach.miss_km,
            ta=after.approach.tca_utc(after.window.start_utc),
        ) + self._edge()

    def _sampled_line(self) -> str:
        """Sized to the target on the nominal, or the whole budget short of it there; then what it buys at P5."""
        template = SAMPLED_RESPONSE_LINE if self.sized.reached else SAMPLED_RESPONSE_SHORT
        return template.format(
            dv=self.delta_v_km_s * _M_S_PER_KM_S, axis=self.sized.axis.value, sense=self._sense, at=self.burn_at_utc,
            target=self.target_km, buys=self.buys_km, p5b=self.sampled_before_p5_km, p5a=self.sampled_after_p5_km,
            budget=self.budget_km_s * _M_S_PER_KM_S, nominal=self.sized.after.approach.miss_km,
        ) + self._under_target()

    def _under_target(self) -> str:
        burnt = self.sized.burn is not None
        p5 = self.sampled_after_p5_km if burnt else self.sampled_before_p5_km
        if p5 is None or p5 >= self.target_km:
            return ""
        counted = self.sampled_under_target
        share = _AT_LEAST_ONE_IN_20 if counted is None else f"{counted[0]:,} of {counted[1]:,}"
        return (SAMPLED_UNDER_TARGET if burnt else SAMPLED_NONE_UNDER_TARGET).format(
            p5a=p5, target=self.target_km, share=share,
        )

    def _edge(self) -> str:
        after = self.sized.after
        if not (after.approach.at_window_edge and after.approach.tca_s > 0.0):
            return ""
        return RESPONSE_EDGE.format(end=after.window.start_utc + timedelta(seconds=after.window.span_s))

    @property
    def note(self) -> str:
        """The delta-V's basis note: when, on which axis and sense, and how its size was found."""
        if self.sized.burn is None:
            return RESPONSE_NONE_NOTE.format(target=self.target_km)
        axis = self.sized.axis.value
        axis_basis = (
            _LIBRARY_AXIS.format(axis=axis, lead=self.sized.lead_s / 3600.0) if self.sized.from_library
            else _ENTERED_AXIS.format(axis=axis)
        )
        reached = self.sized.reached
        size = (_SIZE_REACHED if reached else _SIZE_SHORT).format(
            target=self.target_km, budget=self.budget_km_s * _M_S_PER_KM_S,
        )
        return RESPONSE_DV_NOTE.format(
            dv=self.delta_v_km_s * _M_S_PER_KM_S, at=self.burn_at_utc, axis_basis=axis_basis, size=size,
            search=_SEARCH_REACHED if reached else _SEARCH_SHORT,
        )


def tca_uncertainty(position_error_km: float, closing_speed_km_s: float, span_s: float, *, at_edge: bool) -> TcaUncertainty:
    """Position error over closing speed; no sigma at an edge, at a speed of rounding noise or none, or past the span."""
    sigma: float | None = None
    speed_known = not math.isnan(closing_speed_km_s)
    if not at_edge and speed_known and closing_speed_km_s >= SLOWEST_CLOSING_KM_S:
        sigma = position_error_km / closing_speed_km_s
        if sigma > span_s:
            sigma = None
    return TcaUncertainty(sigma, position_error_km, closing_speed_km_s, span_s, at_edge)


# ── The sampled TCAs as a histogram (SPC-124) ──

#: The bin widths a histogram may take, s: 1, 2, 5, 10, 15 and 30 s; the same in minutes; 1, 2, 3, 6 and 12 h.
_BIN_LADDER_S = (
    1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1800.0, 3600.0, 7200.0, 10_800.0, 21_600.0,
    43_200.0,
)
#: A histogram is drawn in about this many bins, unless the samples' own TCA uncertainty makes them wider.
_BINS_ACROSS_RANGE = 20.0
HISTOGRAM_CAPTION = (
    "Times of closest approach of {n} of {total} samples, in bins of {bin}, no narrower than {pm}, the median "
    "uncertainty of the drawn samples' TCAs from element-set error; {wider}. Not shown: {closing} still closing when "
    "the search ended and {opening} already opening when it began, whose smallest separation is at an edge, not an "
    "encounter, and {unfixed} closing too slowly to fix a time within the span searched."
)


def _bin_label(width_s: float) -> str:
    if width_s < _SECONDS_PER_MINUTE:
        return f"{width_s:.0f} s"
    if width_s < _SECONDS_PER_HOUR:
        return f"{width_s / _SECONDS_PER_MINUTE:.0f} min"
    return f"{width_s / _SECONDS_PER_HOUR:.0f} h"


def _wider_text(n_wider: int) -> str:
    """How many drawn samples are known less well than a bin: the median floors the bins, so up to half may be."""
    if n_wider == 0:
        return "every drawn sample's uncertainty is within a bin"
    if n_wider == 1:
        return "1 drawn sample's uncertainty is wider than a bin"
    return f"{n_wider} drawn samples' uncertainties are wider than a bin"


def _clock(seconds: float, *, with_seconds: bool) -> str:
    """Whole seconds after the scenario epoch as h:mm, or h:mm:ss: an edge is a whole multiple of a whole-second width,
    so this states it exactly."""
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if with_seconds else f"{hours}:{minutes:02d}"


def bin_width_s(range_s: float, median_sigma_s: float) -> float:
    """The smallest width on the ladder at least the wider of a twentieth of *range_s* and *median_sigma_s*; whole
    12 h steps beyond it."""
    least = max(range_s / _BINS_ACROSS_RANGE, median_sigma_s)
    widest = _BIN_LADDER_S[-1]
    return next((w for w in _BIN_LADDER_S if w >= least), math.ceil(least / widest) * widest)


@dataclass(frozen=True)
class TcaHistogram:
    """A sampled cell's TCAs, hours after the scenario epoch, in bins no narrower than the median sample's uncertainty.

    Samples whose smallest separation is at an edge of the search are counted, not drawn: they are not encounters.
    Nor are samples closing too slowly to fix a time within the span: they have no time to draw. Of those drawn, the
    caption says how many are known less well than a bin.
    """

    bin_width_s: float
    edges_h: tuple[float, ...]
    counts: tuple[int, ...]
    n_shown: int
    n_closing_at_end: int
    n_opening_at_start: int
    median_sigma_s: float
    n_unfixed: int = 0
    n_wider: int = 0

    @property
    def caption(self) -> str:
        """What the bars hold, how wide they are and why, how many drawn are known less well, and what is left out."""
        total = self.n_shown + self.n_closing_at_end + self.n_opening_at_start + self.n_unfixed
        return HISTOGRAM_CAPTION.format(
            n=self.n_shown, total=total, bin=_bin_label(self.bin_width_s), pm=sigma_text(self.median_sigma_s),
            wider=_wider_text(self.n_wider), closing=self.n_closing_at_end, opening=self.n_opening_at_start,
            unfixed=self.n_unfixed,
        )

    @property
    def _with_seconds(self) -> bool:
        return self.bin_width_s < _SECONDS_PER_MINUTE

    @property
    def clock_unit(self) -> str:
        """How the table and the chart state each edge: h:mm, or h:mm:ss for bins under a minute."""
        return "h:mm:ss" if self._with_seconds else "h:mm"

    @property
    def rows(self) -> tuple[tuple[str, str, int], ...]:
        """Each bin as the table shows it: from, to, and how many samples. The edges are stated, not rounded."""
        clock = [_clock(e * _SECONDS_PER_HOUR, with_seconds=self._with_seconds) for e in self.edges_h]
        return tuple((lo, hi, n) for (lo, hi), n in zip(pairwise(clock), self.counts, strict=True))

    @property
    def chart_data(self) -> dict[str, list[float] | list[int]]:
        """Numbers only, for the chart's JSON: nothing the operator typed can reach the script. The chart labels its
        bars from the table's stated edges."""
        return {"edges_h": list(self.edges_h), "counts": list(self.counts)}


def tca_histogram(
    tcas_h: Sequence[float], sigmas_s: Sequence[float | None], *, n_closing: int, n_opening: int,
) -> TcaHistogram | None:
    """The samples' TCAs, hours after the scenario epoch, each with its own sigma, binned no narrower than the median
    sigma of those drawn. A sample with no sigma has no time to draw and is counted instead. None with no sample to
    draw."""
    fixed = [(t, s) for t, s in zip(tcas_h, sigmas_s, strict=True) if s is not None]
    if not fixed:
        return None
    seconds = np.asarray([t for t, _ in fixed], dtype=float) * _SECONDS_PER_HOUR
    sigmas = np.asarray([s for _, s in fixed], dtype=float)
    median = float(np.median(sigmas))
    width = bin_width_s(float(seconds.max() - seconds.min()), median)
    low = math.floor(float(seconds.min()) / width) * width
    n_bins = max(1, math.ceil((float(seconds.max()) - low) / width))
    edges = low + width * np.arange(n_bins + 1)
    counts, _ = np.histogram(seconds, bins=edges)
    return TcaHistogram(
        width, tuple(float(e) / _SECONDS_PER_HOUR for e in edges), tuple(int(c) for c in counts), len(fixed),
        n_closing, n_opening, median, n_unfixed=len(tcas_h) - len(fixed), n_wider=int(np.sum(sigmas > width)),
    )
