"""The mission harness: every Orbital Watch mission played by its own words in the real console (SPC-248, design 9).

For each mission, in campaign order, on the bundled element sets with no UDL, inside the training page's console frame:

● it starts the mission as the page does (an htmx request, so its events reach the page) and reads the alert;
● every briefing figure is computed again here, independently of the engine (the sgp4 package and this file's own
  sidereal time, the bundled watchlist read as JSON), and must appear in the alert exactly as the engine formatted it;
● every control an objective or the first action names must exist in the console under that name, and every hint's
  spotlight selector must find an element in it;
● each objective is then played as its text and controls say, in the console, with no player per objective: the
  harness finds the object the text names (a role placeholder, or the one named before), does the work a condition's
  check binds, and reads the control the objective lists (an element card term, the intelligence card, the screening's
  summary, first actor, verdict or #, or the sweep's Red HRR counts). The reading must be correct against the
  independent computation for THAT control within the tolerance, at a precision the tolerance accepts, and the engine
  must accept it: an objective whose words name one control while its quantity is another fails here;
● the mission is finished with every objective met, which earns its first star and opens the next mission, and the
  debrief must show each reading given as the accepted answer.

Screening figures (candidates, the first-ranked actor, verdicts, ranks) are graded on the operator's own screening, so
the console's reading is the comparison. Drift is checked against SGP4's longitude change over a sidereal day, the
burn's part by Clohessy-Wiltshire; the red count against the bundled watchlist in the interceptor's own regime.

The missions build on each other (each opens with a star on the one before), so the tests run in campaign order in one
module, as the one admin of the browser session.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sgp4.api import Satrec, jday

from tests.browser.conftest import Console

_REPO = Path(__file__).resolve().parents[2]
_MISSIONS = _REPO / "spectre" / "training" / "config" / "missions.yaml"
_WATCHLIST = json.loads((_REPO / "spectre" / "data" / "hrr_default.json").read_text("utf-8"))[0]["msgBody"]
_INTEL = json.loads((_REPO / "spectre" / "data" / "adversary_intel.json").read_text("utf-8"))
_RED = {"CHN", "RUS", "IRN", "PRK"}
_BY_SATNO = {o["satNo"]: o for o in _WATCHLIST}
_BY_NAME = {o["commonName"]: o for o in _WATCHLIST}
_SIDEREAL_DAY_MIN = 1436.0682

#: The CSRF-carrying POST from inside the page, as htmx would make it.
_POST = """([path, form]) => fetch(path, {method: 'POST',
  headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content},
  body: new URLSearchParams(form)}).then(r => r.text().then(t => [r.status, t]))"""

#: The HUD read through its contract hooks: each objective's status and, for a choice, its options by label.
_HUD = """(path) => fetch(path).then(r => r.text()).then(html => {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const out = {};
  doc.querySelectorAll('[data-objective-id]').forEach(li => {
    const options = {};
    li.querySelectorAll('input[name="option_id"]').forEach(i => {
      options[(i.closest('label') || i.parentElement).textContent.trim()] = i.value; });
    out[li.dataset.objectiveId] = {status: li.dataset.status, options: options};
  });
  return out; })"""

#: Whether the console shows a control by this name: the visible words of a tab, button, label, card term, heading,
#: option or option group, or a summary.
_CONTROL = """(name) => {
  const els = document.querySelectorAll('button, label, summary, dt, th, h2, h3, legend, option, span, strong, a');
  for (const el of els) { if ((el.textContent || '').replace(/\\s+/g, ' ').includes(name)) return true; }
  for (const g of document.querySelectorAll('optgroup')) { if ((g.label || '').includes(name)) return true; }
  return false; }"""


# ── Independent figures ──────────────────────────────────────────────────────


def _satrec(tle: str) -> Satrec:
    line1, line2 = tle.splitlines()
    return Satrec.twoline2rv(line1, line2)


def _tle(satno: str) -> str:
    o = _BY_SATNO[satno]
    return f"{o['line1']}\n{o['line2']}"


def _position(tle: str, at: datetime) -> np.ndarray:
    jd, fr = jday(at.year, at.month, at.day, at.hour, at.minute, at.second + at.microsecond / 1e6)
    err, r, _ = _satrec(tle).sgp4(jd, fr)
    assert err == 0
    return np.array(r)


def _state(tle: str, at: datetime) -> tuple[np.ndarray, np.ndarray]:
    jd, fr = jday(at.year, at.month, at.day, at.hour, at.minute, at.second)
    err, r, v = _satrec(tle).sgp4(jd, fr)
    assert err == 0
    return np.array(r), np.array(v)


def _gmst_deg(at: datetime) -> float:
    """Greenwich mean sidereal time by the IAU 1982 expression, written out here, not imported."""
    jd, fr = jday(at.year, at.month, at.day, at.hour, at.minute, at.second)
    t = (jd + fr - 2451545.0) / 36525.0
    seconds = 67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return (seconds / 240.0) % 360.0


def _longitude(tle: str, at: datetime) -> float:
    r = _position(tle, at)
    return (math.degrees(math.atan2(r[1], r[0])) - _gmst_deg(at) + 180.0) % 360.0 - 180.0


def _range(a: str, b: str, at: datetime) -> float:
    return float(np.linalg.norm(_position(a, at) - _position(b, at)))


def _epoch(tle: str) -> datetime:
    field_ = tle.splitlines()[0][18:32]
    year = 2000 + int(field_[:2])
    return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=float(field_[2:]) - 1.0)


def _clock(satnos: list[str]) -> datetime:
    """The mission clock on the bundled sets: they are weeks old, so it is the newest epoch among them."""
    return max(_epoch(_tle(s)) for s in satnos)


def _regime(tle: str) -> str:
    """The regime from the set's mean motion and eccentricity, by the altitude bands written out here."""
    sat = _satrec(tle)
    a = (398600.8 / (sat.no_kozai / 60.0) ** 2) ** (1.0 / 3.0)
    perigee, apogee = a * (1 - sat.ecco) - 6378.135, a * (1 + sat.ecco) - 6378.135
    if apogee < 2000:
        return "LEO"
    if sat.ecco > 0.25:
        return "HEO"
    return "GEO" if perigee > 34000 and apogee < 37500 else "MEO"


def _nearest_blue(red: str, at: datetime) -> tuple[str, float]:
    """The bundled blue object in the red object's regime nearest it at *at*, and the range."""
    regime = _regime(_tle(red))
    blues = [o for o in _WATCHLIST if o["country"] not in _RED and _regime(_tle(o["satNo"])) == regime]
    best = min(blues, key=lambda o: _range(_tle(red), _tle(o["satNo"]), at))
    return best["commonName"], _range(_tle(red), _tle(best["satNo"]), at)


def _cw_offset(n: float, dv: np.ndarray, t: float) -> np.ndarray:
    """The Clohessy-Wiltshire displacement (radial, along, cross; km) *t* s after an impulse *dv* (km/s, same axes)."""
    s, c = math.sin(n * t), math.cos(n * t)
    vr, va, vc = dv
    x = vr / n * s + 2 * va / n * (1 - c)
    y = 2 * vr / n * (c - 1) + va / n * (4 * s - 3 * n * t)
    z = vc / n * s
    return np.array([x, y, z])


def _burned_approach(red: str, blue: str, at: datetime, burn_m_s: tuple[float, float, float],
                     hours: float) -> tuple[datetime, float]:
    """The closest approach after an impulse on *red* at *at*: its unburned SGP4 path plus the CW displacement."""
    n = 2 * math.pi / (1436.0682 * 60.0)
    dv = np.array(burn_m_s) / 1000.0
    best = (at, float("inf"))
    for step in range(int(hours * 3600) // 20 + 1):
        t = at + timedelta(seconds=20 * step)
        r, v = _state(_tle(red), t)
        radial = r / np.linalg.norm(r)
        cross = np.cross(r, v) / np.linalg.norm(np.cross(r, v))
        along = np.cross(cross, radial)
        offset = _cw_offset(n, dv, 20.0 * step)
        position = r + offset[0] * radial + offset[1] * along + offset[2] * cross
        d = float(np.linalg.norm(position - _position(_tle(blue), t)))
        if d < best[1]:
            best = (t, d)
    return best


def _burned_period(red: str, at: datetime, burn_m_s: tuple[float, float, float]) -> float:
    """The set's mean period after the burn: its own period, moved by the change the burn makes to the osculating one."""
    r, v = _state(_tle(red), at)
    radial = r / np.linalg.norm(r)
    cross = np.cross(r, v) / np.linalg.norm(np.cross(r, v))
    along = np.cross(cross, radial)
    dv = (burn_m_s[0] * radial + burn_m_s[1] * along + burn_m_s[2] * cross) / 1000.0

    def period(vel: np.ndarray) -> float:
        a = 1.0 / (2.0 / np.linalg.norm(r) - float(np.dot(vel, vel)) / 398600.8)
        return 2 * math.pi * math.sqrt(a ** 3 / 398600.8) / 60.0

    own = 2 * math.pi / _satrec(_tle(red)).no_kozai
    return own + period(v + dv) - period(v)


# ── The page ────────────────────────────────────────────────────────────────


@dataclass
class Flight:
    """One mission being flown: the training page, its console frame, and what the harness has read."""

    page: Any
    mission: str
    frame: Any = None
    alert: str = ""
    read: dict[str, str] = field(default_factory=dict)

    def post(self, path: str, form: dict[str, str] | None = None) -> tuple[int, str]:
        status, text = self.page.evaluate(_POST, [path, form or {}])
        return int(status), str(text)

    def hud(self) -> dict[str, Any]:
        return dict(self.page.evaluate(_HUD, f"/training/m/{self.mission}/hud"))

    def until(self, test: Callable[[], bool], what: str, timeout_s: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not test():
            assert time.monotonic() < deadline, f"{self.mission}: never {what}"
            self.page.wait_for_timeout(250)

    def text(self, selector: str) -> str:
        return " ".join(str(self.frame.locator(selector).first.text_content() or "").split())


def _yaml() -> dict[str, Any]:
    import yaml

    return dict(yaml.safe_load(_MISSIONS.read_text("utf-8")))


_MISSION_ORDER = [m["id"] for m in _yaml()["missions"]]


def _spec(mission_id: str) -> dict[str, Any]:
    return next(m for m in _yaml()["missions"] if m["id"] == mission_id)


def _start(console: Console, mission_id: str) -> Flight:
    page = console.open("/training")
    page.wait_for_selector("#tpanel-dashboard .spinner", state="detached", timeout=30000)
    flight = Flight(page, mission_id)
    if _spec(mission_id)["chapter"] == "shadows":
        # Chapter 2 needs Observer: the Orientation tutorial and the points the first chapter paid.
        flight.post("/training/tutorial/orientation/complete")
    page.evaluate("() => document.body.insertAdjacentHTML('beforeend', '<div id=\"harness-stage\"></div>')")
    page.evaluate(f"() => htmx.ajax('POST', '/training/m/{mission_id}/start', "
                  "{target: '#harness-stage', swap: 'innerHTML'})")
    flight.until(lambda: bool(page.inner_text("#harness-stage").strip()), "showed the alert")
    flight.alert = " ".join(page.inner_text("#harness-stage").split())
    assert "Locked" not in flight.alert and "cannot start" not in flight.alert, flight.alert
    page.click("#tnav-console")
    page.frame_locator("#training-console-frame").locator("#blue-list").wait_for(state="attached", timeout=30000)
    flight.frame = next(f for f in page.frames if f.parent_frame is not None and "frame=training" in f.url)
    flight.frame.wait_for_load_state("networkidle")
    return flight


def _controls_exist(flight: Flight, names: list[str], where: str) -> None:
    missing = [n for n in names if not flight.frame.evaluate(_CONTROL, n)]
    assert not missing, f"{flight.mission} {where}: the console has no control named {missing}"


# ── Console steps, as the instructions say them ─────────────────────────────


def _open_card(flight: Flight, side: str, name: str) -> None:
    """Assets, then Blue or Red, then the object's card."""
    flight.frame.click("button.stab[data-panel='sb-assets']")
    flight.frame.click(f"button.atab[data-panel='at-{side}']")
    summary = flight.frame.locator(f"#{side}-list details.elset-card summary", has_text=name)
    summary.click()


def _card_value(flight: Flight, side: str, name: str, term: str) -> str:
    card = flight.frame.locator(f"#{side}-list details.elset-card", has_text=name)
    return " ".join(str(card.locator(f"dt:text-is('{term}') + dd").text_content() or "").split())


def _screen(flight: Flight, name: str) -> None:
    """Asset Screening, Blue Asset *name*, Screen Asset; wait for its results."""
    frame = flight.frame
    frame.click("button.htab[data-panel='hero-screen']")
    frame.wait_for_selector("#scr-asset")
    frame.select_option("#scr-asset", value=_BY_NAME[name]["satNo"])
    frame.click("#threat-screen-form button:has-text('Screen Asset')")
    frame.wait_for_selector("#threat-screen-results .threat-sweep-result", timeout=120000)


def _verdict_of(flight: Flight, actor: str) -> str:
    row = flight.frame.locator("#threat-screen-results tr.threat-parent", has=flight.frame.locator(
        f"td strong:text-is('{actor}')"))
    return " ".join(str(row.locator("td").nth(4).text_content() or "").split())


def _choose_red_in_sweep(flight: Flight, name: str) -> None:
    frame = flight.frame
    frame.click("button.htab[data-panel='hero-sweep']")
    frame.select_option("#ts-red-sat", value=name)
    frame.wait_for_selector("#ts-red-orbit-info .red-orbit-info", timeout=30000)


def _intercepts(flight: Flight, red: str, blue: str, side: str) -> None:
    """Intercept Engine: Red Satellite, Blue Satellite, Manoeuvring satellite, Calculate All Intercepts."""
    frame = flight.frame
    frame.click("button.htab[data-panel='hero-engine']")
    frame.click("button.etab[data-panel='et-calculator']")
    frame.select_option("#ie-red-sat", value=red)
    frame.select_option("#ie-blue-sat", value=blue)
    frame.select_option("#ie-manoeuvring", value=side)
    before = frame.locator("#intercept-result").inner_html()
    frame.click("#intercept-engine-form button[type=submit]")
    flight.until(lambda: frame.locator("#intercept-result").inner_html() != before
                 and frame.locator("#intercept-result table").count() > 0, "showed the intercepts", 180)


# ── The bound objects, found here independently ─────────────────────────────


@dataclass
class Cast:
    """Each role's object, found here as the mission file defines it: a fixed catalogue number, or the blue object
    nearest another role at the clock, computed here; and the mission clock and any inject."""

    names: dict[str, str]
    sides: dict[str, str]
    satnos: dict[str, str]
    clock: datetime
    burn: tuple[float, float, float] | None = None
    injected: str = ""


def _cast(spec: dict[str, Any]) -> Cast:
    roles = spec["roles"]
    fixed = {name: r["satno"] for name, r in roles.items() if "satno" in r}
    clock = _clock(list(fixed.values()))
    satnos = dict(fixed)
    for name, r in roles.items():
        if "nearest_to" in r:
            satnos[name] = _BY_NAME[_nearest_blue(fixed[r["nearest_to"]], clock)[0]]["satNo"]
    inject = spec.get("inject")
    return Cast({n: _BY_SATNO[s]["commonName"] for n, s in satnos.items()}, {n: r["side"] for n, r in roles.items()},
                satnos, clock, tuple(float(x) for x in inject["burn_m_s"]) if inject else None,  # type: ignore[arg-type]
                inject["role"] if inject else "")


def _roles_in(text: str, cast: Cast) -> list[str]:
    """The roles a mission text names, in the order it names them."""
    return [r for r in re.findall(r"\{(\w+)", text) if r in cast.names]


# ── Independent truths, by what the console reading is ──────────────────────

_LINE2 = {"Inclination": (8, 16), "RAAN": (17, 25), "Arg. of perigee": (34, 42), "Mean anomaly": (43, 51)}
CARD_TERMS = ("Sub-satellite lon.", "Inclination", "RAAN", "Arg. of perigee", "Mean anomaly", "Period", "Regime")


def _burned_drift(red: str, at: datetime, burn: tuple[float, float, float] | None) -> float:
    """How far the longitude under *red* moves over a sidereal day, degrees east: SGP4 on its own set, plus the
    along-track displacement the burn makes in that day by Clohessy-Wiltshire, as an angle at its radius."""
    later = at + timedelta(minutes=_SIDEREAL_DAY_MIN)
    moved = (_longitude(_tle(red), later) - _longitude(_tle(red), at) + 180) % 360 - 180
    if burn is None:
        return moved
    n = 2 * math.pi / (_SIDEREAL_DAY_MIN * 60.0)
    along = _cw_offset(n, np.array(burn) / 1000.0, _SIDEREAL_DAY_MIN * 60.0)[1]
    return moved + math.degrees(along / float(np.linalg.norm(_position(_tle(red), at))))


def _card_truth(term: str, role: str, cast: Cast) -> Any:
    """What an element card term reads for *role*, from the set itself; None where the inject changed it and no
    independent figure is made here (only the Period of an injected object is)."""
    satno, tle = cast.satnos[role], _tle(cast.satnos[role])
    if role == cast.injected:
        return _burned_period(satno, cast.clock, cast.burn) if term == "Period" and cast.burn else None
    if term == "Sub-satellite lon.":
        return _longitude(tle, cast.clock)
    if term == "Period":
        return 2 * math.pi / _satrec(tle).no_kozai
    if term == "Regime":
        return _regime(tle)
    lo, hi = _LINE2[term]
    return float(tle.splitlines()[1][lo:hi])


def _drift_truth(role: str, cast: Cast) -> str:
    rate = _burned_drift(cast.satnos[role], cast.clock, cast.burn if role == cast.injected else None)
    return "east" if rate > 0 else "west"


def _alert_truths(spec: dict[str, Any], cast: Cast) -> list[str]:
    """The figures the alert and brief must hold, formatted as the mission file formats them, computed here."""
    expected = [cast.clock.strftime("%d %b %Y %H:%M UTC")] if "{clock}" in " ".join(spec["brief"]) else []
    for q in spec["quantities"].values():
        if q["fn"] != "range_km":
            continue
        a, b, hours = cast.satnos[q["args"]["a"]], cast.satnos[q["args"]["b"]], float(q["args"].get("hours", 0))
        expected.append(f"{_range(_tle(a), _tle(b), cast.clock + timedelta(hours=hours)):.1f} km")
    expected += [cast.names[r] for r in cast.names]
    return expected


# ── Reading the console, as the objective's controls and words say ──────────


def _reading(flight: Flight, objective: dict[str, Any], cast: Cast, subject: str) -> tuple[str, Any]:
    """Do what the objective's words say in the console and read what its controls name: the reading the operator
    would give, and the independent truth for it where one is made here (None where the operator's own screening is
    what grades it)."""
    controls, text = objective.get("controls", []), objective["text"]
    named = _roles_in(text, cast)
    actor = named[-1] if named else subject
    term = next((c for c in controls if c in CARD_TERMS), "")
    if term:
        side = cast.sides[subject]
        _open_card(flight, side, cast.names[subject])
        shown = _card_value(flight, side, cast.names[subject], term).split(" at ")[0]
        return shown, _card_truth(term, subject, cast)
    if "UNCLASS // PAIR" in controls:
        _choose_red_in_sweep(flight, cast.names[subject])
        level = flight.frame.locator("#ts-red-orbit-info span[title^='Analyst judgement']")
        record = _INTEL[cast.satnos[subject]]
        if "threat level" in text:
            return " ".join(str(level.first.text_content()).split()), record["threat_level"]
        shown = flight.frame.evaluate("""() => document.querySelector(
          "#ts-red-orbit-info span[title^='Analyst judgement']").parentElement.nextElementSibling.textContent.trim()""")
        return str(shown), record["assessed_threat"]
    return _screen_or_sweep_reading(flight, controls, text, cast, subject, actor)


# Six facts of one reading: the flight, what the objective names and says, its cast, and the two objects it is about.
def _screen_or_sweep_reading(  # noqa: PLR0913, PLR0917
    flight: Flight, controls: list[str], text: str, cast: Cast, subject: str,
    actor: str,
) -> tuple[str, Any]:
    if "candidate actor" in controls:
        match = re.search(r"(\d+) candidate actor", flight.text("#threat-screen-results .threat-sweep-summary"))
        assert match
        return match.group(1), None
    if "MOST DANGEROUS ACTOR" in controls:
        return str(flight.frame.evaluate("""() => [...document.querySelectorAll('#threat-screen-results span')]
          .find(e => e.textContent.trim() === 'MOST DANGEROUS ACTOR').nextElementSibling.textContent.trim()""")), None
    if "Verdict" in controls:
        return _verdict_of(flight, cast.names[actor]) or "Not ranked", None
    if "#" in controls:
        return _rank_of(flight, cast.names[actor]), None
    if "Red HRR" in controls:
        labels = flight.frame.eval_on_selector_all("#ts-tgt-group optgroup[label='Red HRR'] option",
                                                   "els => els.map(e => e.textContent)")
        shown = str(sum(int(re.search(r"\((\d+) object", t).group(1)) for t in labels))  # type: ignore[union-attr]
        regime = _regime(_tle(cast.satnos[subject]))
        return shown, sum(1 for o in _WATCHLIST if o["country"] in _RED and _regime(_tle(o["satNo"])) == regime)
    if "drift" in text:
        side = cast.sides[subject]
        _open_card(flight, side, cast.names[subject])
        period = float(_card_value(flight, side, cast.names[subject], "Period").split()[0])
        return ("east" if period < _SIDEREAL_DAY_MIN else "west"), _drift_truth(subject, cast)
    raise AssertionError(f"{flight.mission}: no reading for {controls} {text!r}")


def _rank_of(flight: Flight, actor: str) -> str:
    rows = flight.frame.locator("#threat-screen-results tr.threat-parent")
    for i in range(rows.count()):
        if rows.nth(i).locator(f"td strong:text-is('{actor}')").count():
            return " ".join(str(rows.nth(i).locator("td").first.text_content()).split())
    return "0"


def _condition(flight: Flight, objective: dict[str, Any], cast: Cast) -> None:
    """Do the work the condition's words name, with the objects its check binds."""
    check = objective["check"]
    if check["type"] == "screening_run":
        _screen(flight, cast.names[check["asset"]])
    elif check["type"] == "intercept_run":
        _intercepts(flight, cast.names[check["red"]], cast.names[check["blue"]], check["manoeuvring"])
    elif check["type"] == "sweep_run":
        frame = flight.frame
        _choose_red_in_sweep(flight, cast.names[check["red"]])
        frame.wait_for_selector("#ts-tgt-group")
        frame.select_option("#ts-tgt-group", value="all")
        frame.wait_for_timeout(1500)
        before = frame.locator("#threat-sweep-results").inner_html()
        frame.click("#ts-target-config button:has-text('Sweep Targets')")
        flight.until(lambda: frame.locator("#threat-sweep-results").inner_html() != before
                     and "Sweeping" not in frame.locator("#threat-sweep-results").inner_text(), "swept", 300)


# ── Checks ───────────────────────────────────────────────────────────────────


def _number(shown: str) -> tuple[float, int]:
    """The figure in a console reading, signed for a west longitude, and how many decimals it was shown to."""
    match = re.search(r"(-?\d+(?:\.(\d+))?)", shown)
    assert match, shown
    value = float(match.group(1)) * (-1.0 if shown.strip().endswith("W") else 1.0)
    return value, len(match.group(2) or "")


def _check_answer(flight: Flight, objective: dict[str, Any], shown: str, truth: Any) -> None:
    """The console's reading is shown precisely enough for the tolerance, and right against the independent truth."""
    value, decimals = _number(shown)
    tolerance = float(objective["tolerance"])
    assert 0.5 * 10 ** -decimals <= tolerance, f"{objective['id']}: shown to {decimals} places, tolerance {tolerance}"
    if truth is not None:
        error = abs((value - truth + 180) % 360 - 180) if objective["unit"] == "deg" else abs(value - truth)
        assert error <= tolerance, f"{flight.mission} {objective['id']}: console {shown}, independent {truth}"


def _check_alert(flight: Flight, spec: dict[str, Any], cast: Cast) -> None:
    for expected in _alert_truths(spec, cast):
        assert expected in flight.alert, f"{flight.mission}: alert lacks {expected!r}: {flight.alert}"
    if cast.burn is not None:
        target = next(r for r, s in cast.sides.items() if s == "blue")
        when, distance = _burned_approach(cast.satnos[cast.injected], cast.satnos[target], cast.clock, cast.burn, 24)
        match = re.search(r"Closest approach in the next day: ([\d.]+) km at (\d\d \w\w\w \d\d:\d\d) UTC", flight.alert)
        assert match, flight.alert
        shown_when = datetime.strptime(f"{when.year} {match.group(2)}", "%Y %d %b %H:%M").replace(tzinfo=UTC)
        assert abs(float(match.group(1)) - distance) <= 0.1, (match.group(1), distance)
        assert abs((shown_when - when).total_seconds()) <= 180, (shown_when, when)


def _check_debrief(flight: Flight, debrief: str, given: dict[str, str]) -> None:
    """The debrief shows every reading the operator gave as the accepted answer, and its note's figures."""
    text = " ".join(debrief.split())
    for oid, reading in given.items():
        assert reading in text, f"{flight.mission} debrief lacks {oid}'s accepted {reading!r}"


# ── The test ─────────────────────────────────────────────────────────────────


def _play(flight: Flight, spec: dict[str, Any], cast: Cast) -> dict[str, str]:
    given: dict[str, str] = {}
    subject = _roles_in(spec["first_action"]["say"], cast)[-1]
    for objective in spec["objectives"]:
        oid = objective["id"]
        named = _roles_in(objective["text"], cast)
        subject = named[0] if named else subject
        # The hint is offered from the moment the operator reaches the objective: its spotlight must show there.
        spotlight = (objective.get("hint") or {}).get("spotlight")
        if spotlight:
            assert flight.frame.locator(f"{spotlight} >> visible=true").count() > 0, (
                f"{spec['id']} {oid}: nothing visible for the spotlight {spotlight!r} when the hint is offered")
        if objective["kind"] == "condition":
            _condition(flight, objective, cast)
            _controls_exist(flight, objective.get("controls", []), f"objective {oid}")
            flight.until(lambda o=oid: flight.hud()[o]["status"] == "met", f"met {oid}")
            continue
        reading, truth = _reading(flight, objective, cast, subject)
        _controls_exist(flight, objective.get("controls", []), f"objective {oid}")
        assert reading, f"{spec['id']} {oid}: nothing read from the console"
        if objective["kind"] == "answer":
            _check_answer(flight, objective, reading, truth)
            status, body = flight.post(f"/training/m/{spec['id']}/answer", {"objective_id": oid, "value": reading})
        else:
            if truth is not None:
                assert reading == truth, f"{spec['id']} {oid}: console {reading!r}, independent {truth!r}"
            options = flight.hud()[oid]["options"]
            assert reading in options, f"{spec['id']} {oid}: {reading!r} is not among {list(options)}"
            status, body = flight.post(f"/training/m/{spec['id']}/choose",
                                       {"objective_id": oid, "option_id": options[reading]})
        assert status == 200, body
        assert flight.hud()[oid]["status"] == "met", f"{spec['id']} {oid}: {reading!r} not accepted"
        given[oid] = reading
    return given


@pytest.mark.parametrize("mission_id", _MISSION_ORDER)
def test_the_mission_plays_by_its_own_words(console: Console, mission_id: str) -> None:
    spec = _spec(mission_id)
    cast = _cast(spec)
    flight = _start(console, mission_id)
    _check_alert(flight, spec, cast)
    _controls_exist(flight, spec["first_action"].get("controls", []), "first action")
    given = _play(flight, spec, cast)
    status, body = flight.post(f"/training/m/{mission_id}/finish")
    assert status == 200, body
    _check_debrief(flight, body, given)
    assert console.problems() == []
