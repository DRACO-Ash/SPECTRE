"""SPECTRE: Orbital Watch's presentation in Chromium, under the console's policy (SPC-248).

The campaign tab, the alert, the HUD docked beside the console frame, the spotlight a hint draws inside that frame,
and the debrief. The mission routes (spectre/web/routes/missions.py) belong to the engine slice, so each test answers
/training/m/... itself: the real templates are rendered in this process with a fixture context shaped exactly as the
contract in the 0.48.0 build brief fixes, and handed to the live page through an intercepted request, the way
tests/browser/conftest.py lands fragments a throwaway instance cannot produce. Everything else (the training page,
the console in its frame, htmx, core.js, training.js, mission.js and the policy) is the real thing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from tests.browser.conftest import Browser, Console

_INTEL = json.loads((Path(__file__).resolve().parents[2] / "spectre/data/adversary_intel.json").read_text("utf-8"))
#: A console control the hint's spotlight ringed in these tests: the Asset Screening tab.
_SCREENING_TAB = '.htab[data-panel="hero-screen"]'
_MISSION = "inspector"
_NEXT = "listener"

#: A stand-in for WebAudio that records each note's frequency, so a test can hear what the page played.
_FAKE_AUDIO = """
window.__tones = []; window.__audioContexts = 0;
window.AudioContext = function () {
  window.__audioContexts++;
  this.currentTime = 0; this.state = 'running'; this.destination = {};
  const param = { setValueAtTime() {}, exponentialRampToValueAtTime() {} };
  this.createOscillator = () => ({ type: '', connect() {}, start() {}, stop() {},
    frequency: { setValueAtTime: (f) => window.__tones.push(f) } });
  this.createGain = () => ({ gain: param, connect() {} });
};
"""

#: The WCAG contrast of each matched element's text against the backgrounds it is painted on, composited.
_CONTRAST = """(selectors) => {
  const parse = (c) => { const m = c.match(/[\\d.]+/g).map(Number); return [m[0], m[1], m[2], m.length > 3 ? m[3] : 1]; };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const backdrop = (el) => { const chain = []; for (let e = el; e; e = e.parentElement) chain.unshift(e);
    let bg = [255, 255, 255];
    for (const e of chain) { const [r, g, b, a] = parse(getComputedStyle(e).backgroundColor);
      bg = [r * a + bg[0] * (1 - a), g * a + bg[1] * (1 - a), b * a + bg[2] * (1 - a)]; }
    return bg; };
  const out = [];
  for (const sel of selectors) for (const el of document.querySelectorAll(sel)) {
    if (!el.offsetParent || !el.textContent.trim()) continue;
    const cs = getComputedStyle(el); const fg = parse(cs.color); const bg = backdrop(el);
    const blended = [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
    const [hi, lo] = [lum(blended), lum(bg)].sort((x, y) => y - x);
    const size = parseFloat(cs.fontSize); const bold = Number(cs.fontWeight) >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    out.push({ sel, text: el.textContent.trim().slice(0, 40), ratio: (hi + 0.05) / (lo + 0.05), floor: large ? 3 : 4.5 });
  }
  return out;
}"""


def _render(template: str, **context: Any) -> str:
    from spectre.web.app import templates

    return templates.env.get_template(template).render(**context)


def _assert_clean(console: Console, *expected: int) -> None:
    """No policy violation, uncaught exception or console error, beyond Chromium's own line for each *expected*
    HTTP status a test made the server answer (it logs every 4xx and 5xx a request gets; no script can stop that)."""
    allowed = tuple(f"the server responded with a status of {code}" for code in expected)
    assert [p for p in console.problems() if not (allowed and any(a in p for a in allowed))] == []


def _until(page: Any, expression: str, timeout_s: float = 10.0) -> None:
    """Poll *expression* until true: wait_for_function re-evaluates a string with eval, which the policy refuses."""
    deadline = time.monotonic() + timeout_s
    while not page.evaluate(expression):
        assert time.monotonic() < deadline, f"never true: {expression}"
        page.wait_for_timeout(50)


# ── Fixture contexts, shaped as the contract fixes them ─────────────────────────


def _mission_node(mid: str, title: str, **extra: Any) -> dict[str, Any]:
    node = {"id": mid, "title": title, "alert_line": "", "par_seconds": 240, "stars": 0, "best_score": 0,
            "locked": False, "lock_reason": "", "needs_udl": False}
    node.update(extra)
    return node


def campaign_context(running: dict[str, str] | None = None) -> dict[str, Any]:
    first_watch = [
        _mission_node("know_your_asset", "Know your asset", stars=3, best_score=450, par_seconds=180,
                      alert_line="SKYNET 5A is yours. Find it."),
        _mission_node("who_is_near", "Who is near?", stars=1, best_score=220,
                      alert_line="Something is near SKYNET 5A. Find out what."),
        _mission_node("the_sweep", "The sweep", par_seconds=300, alert_line="Sweep the watchlist for red objects."),
        _mission_node("read_a_threat", "Read a threat", locked=True, lock_reason="Finish The sweep to open this."),
    ]
    shadows = [
        _mission_node("tug", "The tug", par_seconds=300, locked=True, lock_reason="Opens at Observer."),
        _mission_node(_MISSION, "The inspector", par_seconds=360, locked=True, lock_reason="Opens at Observer."),
        _mission_node(_NEXT, "The listener", locked=True, lock_reason="Opens at Observer.", needs_udl=True),
    ]
    return {
        "chapters": [
            {"id": "first_watch", "title": "First Watch", "blurb": "Learn the console on your own assets.",
             "rank_required": 1, "locked": False, "lock_reason": "", "missions": first_watch},
            {"id": "shadows", "title": "Shadows in the Belt", "blurb": "Proximity operations in GEO.",
             "rank_required": 2, "locked": True, "lock_reason": "Reach Observer: 100 points and 4 stars in Chapter 1.",
             "missions": shadows},
        ],
        "rank": {"level": 1, "title": "Cadet", "points": 670, "next_title": "Observer",
                 "next_conditions": ["100 training points", "4 stars in Chapter 1"]},
        "medals_count": 0,
        "running_mission": running,
    }


def alert_context(*, exercise: bool = True) -> dict[str, Any]:
    intel = _INTEL["50321"]
    return {
        "mission": {"id": _MISSION, "title": "The inspector", "chapter_title": "Chapter 2: Shadows in the Belt"},
        "alert_line": "SY-12 01 manoeuvring. SKYNET 5A is the nearest blue asset.",
        "brief": ["SY-12 01 burned 1.2 m/s along-track at the start of the watch.",
                  "Find when, and how close, it passes SKYNET 5A."],
        "intel_card": {"name": intel["name"], "satno": "50321", "country": intel["country"], "orbit": intel["orbit"],
                       "assessed_threat": intel["assessed_threat"], "significance": intel["significance"],
                       "threat_level": intel["threat_level"], "source": intel["source"]},
        "data_note": "Element sets: bundled, SYNTHETIC",
        "exercise_inject": "SY-12 01 burn of 1.2 m/s along-track at the start. Not observed behaviour." if exercise
        else None,
        "first_action": "Open Asset Screening and screen SKYNET 5A.",
    }


def debrief_context(*, stars: int = 2, rank_up: bool = True) -> dict[str, Any]:
    return {
        "mission": {"id": _MISSION, "title": "The inspector"},
        "stars": stars,
        "star_reasons": [
            {"star": 1, "earned": stars >= 1, "why": "Every objective met."},
            {"star": 2, "earned": stars >= 2, "why": "Finished in 4:12, inside par of 6:00."},
            {"star": 3, "earned": stars >= 3, "why": "One hint used. Fly it with none for the third star."},
        ],
        "score": 375, "seconds": 252, "par_seconds": 360, "hints_used": 1,
        "objectives": [
            {"text": "Screen SKYNET 5A in Asset Screening.", "status": "met", "given": None, "accepted": None,
             "explanation": "Asset Screening ranks every red object by its closest approach."},
            {"text": "Range at closest approach", "status": "met", "given": "412 km", "accepted": "405 to 425 km",
             "explanation": "Closest approach is 414.6 km at 17:42 UTC on the injected orbit."},
        ],
        "best_answer_note": "414.6 km at 17:42 UTC: the Intercept Engine's TCA with SY-12 01 manoeuvring.",
        "unlocked": ["The listener"],
        "next_mission": {"id": _NEXT, "title": "The listener"},
        "rank_up": {"level": 2, "title": "Observer"} if rank_up else None,
        "rank_points_earned": 150,
        "rank_note": None,
        "chapter_complete": {"title": "Shadows in the Belt", "stars": 7, "max_stars": 9},
        "next_lock_reason": "Reach Planner: 3 challenge passes.",
    }


def _objectives() -> list[dict[str, Any]]:
    common = {"status": "open", "points_awarded": 0, "hint_available": True, "hint_cost": 25, "hint_text": None,
              "spotlight": None, "options": [], "answer_unit": None, "miss_band": None}
    return [
        {**common, "id": "screen", "kind": "condition", "text": "Screen SKYNET 5A in Asset Screening.", "points": 100},
        {**common, "id": "range", "kind": "answer", "text": "Range at closest approach", "points": 150,
         "answer_unit": "km"},
        {**common, "id": "move", "kind": "choice", "text": "Which way should SKYNET 5A move?", "points": 125,
         "options": [{"id": "east", "label": "Drift east 0.1°"}, {"id": "west", "label": "Drift west 0.1°"},
                     {"id": "hold", "label": "Hold station"}]},
    ]


_HINTS = {"screen": ("Asset Screening is the second tab along the top.", _SCREENING_TAB),
          "range": ("Run the Intercept Engine with SY-12 01 manoeuvring.", "#intercept-engine-form"),
          "move": ("The Intercept Engine's EVASION rows compare the moves.", None)}



def _five_seconds_ago() -> str:
    return (datetime.now(UTC) - timedelta(seconds=5)).isoformat()

@dataclass
class Game:
    """The mission routes, answered from fixtures: what each request posted, and the HUD's state between them."""

    console: Console
    objectives: list[dict[str, Any]] = field(default_factory=_objectives)
    score: int = 0
    hints_used: int = 0
    reported: set[str] = field(default_factory=set)
    started_at: str = field(default_factory=_five_seconds_ago)
    par_seconds: int = 360
    posts: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    hud_gets: list[float] = field(default_factory=list)
    alert: dict[str, Any] = field(default_factory=alert_context)
    debrief: dict[str, Any] = field(default_factory=debrief_context)
    best_seconds: int | None = None
    #: The mission the server holds open, as the campaign's running_mission says it.
    running: dict[str, str] | None = None
    #: A status to answer an action with instead (and how often), and a delay before answering it.
    refuse: dict[str, int] = field(default_factory=dict)
    #: The reason a refusal gives, by action; the start's lock reason otherwise.
    reasons: dict[str, str] = field(default_factory=dict)
    star_lost: bool = False
    #: Actions whose requests are held unanswered here, to be answered later: a request in flight on demand.
    holding: set[str] = field(default_factory=set)
    held: list[tuple[Any, str]] = field(default_factory=list)
    headers: dict[str, dict[str, str]] = field(default_factory=dict)

    def install(self) -> None:
        self.console.page.route("**/training/m/**", self._answer)

    # The engine's side, as these tests need it.
    def objective(self, oid: str) -> dict[str, Any]:
        return next(o for o in self.objectives if o["id"] == oid)

    def meet(self, oid: str) -> None:
        o = self.objective(oid)
        o["status"], o["points_awarded"] = "met", o["points"]
        self.score += o["points"]

    def meet_all(self) -> None:
        for o in self.objectives:
            if o["status"] != "met":
                self.meet(o["id"])

    def miss(self, oid: str, band: str | None = None) -> None:
        o = self.objective(oid)
        o["status"], o["miss_band"] = "failed", band

    def hud(self, error: str | None = None) -> str:
        met = {o["id"] for o in self.objectives if o["status"] == "met"}
        just_met, self.reported = sorted(met - self.reported), self.reported | met
        return _render("partials/mission_hud.html",
                       mission={"id": _MISSION, "title": "The inspector"},
                       clock={"started_at_iso": self.started_at, "par_seconds": self.par_seconds},
                       objectives=self.objectives, score=self.score, hints_used=self.hints_used,
                       all_met=all(o["status"] == "met" for o in self.objectives), just_met=just_met,
                       error=error, exercise=self.alert["exercise_inject"], best_seconds=self.best_seconds,
                       star_lost=self.star_lost)

    def _post(self, action: str, form: dict[str, str]) -> tuple[int, str]:
        if action in ("start", "restart"):
            self.running = {"id": _MISSION, "title": "The inspector"}
            return 200, _render("partials/mission_alert.html", **self.alert)
        self.running = None if action in ("finish", "abandon") else self.running
        if action == "finish":
            return 200, _render("partials/mission_debrief.html", **self.debrief)
        if action == "abandon":
            return 200, _render("partials/mission_campaign.html", **campaign_context())
        o = self.objective(form["objective_id"])
        given = form.get("value", "").strip()
        if action == "answer" and not given.replace(".", "", 1).isdigit():
            return 422, self.hud(error="Give a number in km.")
        if action == "answer" and given == "412":
            self.meet(o["id"])
        elif action == "answer":
            self.miss(o["id"], "close" if abs(float(given) - 412) < 50 else "far")
        elif action == "choose" and form.get("option_id") == "west":
            self.meet(o["id"])
        elif action == "hint":
            o["hint_text"], o["spotlight"] = _HINTS[o["id"]]
            self.hints_used += 1
            self.score = max(0, self.score - 25)
        return 200, self.hud()

    def _respond(self, request: Any, action: str) -> tuple[int, str, dict[str, str]]:
        if action in self.refuse:
            reason = self.reasons.get(action, "Earn a star on The sweep first.")
            return self.refuse[action], f'<p class="error-msg" role="alert">{reason}</p>', {}
        if request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.post_data or "").items()}
            self.posts.append((action, form))
            code, body = self._post(action, form)
            return code, body, {"HX-Trigger": "training-changed"}
        if action == "campaign":
            return 200, _render("partials/mission_campaign.html", **campaign_context(self.running)), {}
        self.hud_gets.append(time.monotonic())
        return 200, self.hud(), {}

    def release(self, action: str) -> None:
        """Answer the held requests for *action* now, from the state as it stands."""
        self.holding.discard(action)
        for route, held in [h for h in self.held if h[1] == action]:
            self.held.remove((route, held))
            code, body, headers = self._respond(route.request, held)
            route.fulfill(status=code, content_type="text/html; charset=utf-8", body=body, headers=headers)

    def _answer(self, route: Any) -> None:
        action = urlparse(route.request.url).path.rstrip("/").rsplit("/", 1)[-1]
        if action in self.holding:
            self.held.append((route, action))
            return
        code, body, headers = self._respond(route.request, action)
        headers.update(self.headers.get(action, {}))
        route.fulfill(status=code, content_type="text/html; charset=utf-8", body=body, headers=headers)


# ── Driving the page ────────────────────────────────────────────────────────────


def _training(console: Console, game: Game) -> Any:
    game.install()
    page = console.open("/training")
    page.wait_for_selector("#mission-campaign .mission-campaign")
    return page


def _alert(page: Any, game: Game) -> None:
    """Start the inspector from the campaign map as the server would unlock it, and wait for its alert."""
    page.evaluate("htmx.ajax('POST', '/training/m/inspector/start', {target: '#mission-stage', swap: 'innerHTML'})")
    page.wait_for_selector("#mission-alert")


def _take_the_watch(page: Any, game: Game) -> Any:
    _alert(page, game)
    page.click("#mission-take-watch")
    page.wait_for_selector("#mission-hud-dock #mission-hud")
    frame = page.frame_locator("#training-console-frame")
    frame.locator("#blue-list").wait_for(state="attached", timeout=30000)
    return frame


def _gets(game: Game) -> int:
    return len(game.hud_gets)


def _wait_for_poll(page: Any, game: Game, timeout_s: float = 5.0) -> None:
    before = _gets(game)
    deadline = time.monotonic() + timeout_s
    while _gets(game) == before:
        assert time.monotonic() < deadline, "the HUD did not ask again"
        page.wait_for_timeout(50)
    page.wait_for_timeout(200)   # the swap and its init


class TestTheCampaignTab:
    def test_it_is_the_first_tab_and_shows_on_arrival(self, console: Console) -> None:
        page = _training(console, Game(console))
        tabs = page.eval_on_selector_all(".training-nav-btn", "bs => bs.map(b => b.dataset.tab)")
        assert tabs[0] == "campaign"
        assert page.is_visible("#tpanel-campaign")
        assert not page.is_visible("#tpanel-dashboard")
        assert page.text_content("#tnav-scenarios").strip().endswith("Classic scenarios")
        _assert_clean(console)

    def test_chapters_nodes_stars_locks_and_rank(self, console: Console) -> None:
        page = _training(console, Game(console))
        chapters = page.locator(".mission-chapter")
        assert chapters.count() == 2
        assert page.text_content(".mission-rank__title").strip() == "Cadet"
        assert page.get_attribute(".mission-rank svg.mission-insignia", "aria-label") == "Rank insignia: level 1, Cadet"
        assert page.locator(".mission-rank__conditions li").all_text_contents() == [
            "100 training points", "4 stars in Chapter 1"]
        done = page.locator('.mission-node[data-mission-id="know_your_asset"]')
        assert done.get_attribute("data-state") == "done"
        assert done.locator(".mission-star.is-earned").count() == 3
        assert "3 of 3 stars" in done.text_content()
        # The first unlocked mission with no stars is the one the map points at.
        assert page.get_attribute('.mission-node[data-next="true"]', "data-mission-id") == "the_sweep"
        locked = page.locator('.mission-node[data-mission-id="read_a_threat"]')
        assert locked.get_attribute("data-state") == "locked"
        assert locked.locator("button").count() == 0
        assert locked.locator(".mission-node__lock").is_visible()
        assert "Finish The sweep to open this." in locked.text_content()
        assert "Reach Observer" in chapters.nth(1).locator(".mission-lock--chapter").text_content()
        assert page.locator('.mission-node[data-mission-id="listener"] .mission-badge--udl').is_visible()
        assert page.text_content(".mission-campaign__tally").split() == ["4/21", "stars"]   # no medals yet
        _assert_clean(console)

    def test_the_campaign_is_fetched_again_on_training_changed(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        page.evaluate("document.querySelector('.mission-campaign').dataset.marker = 'old'")
        page.evaluate("htmx.trigger(document.body, 'training-changed')")
        page.wait_for_selector(".mission-campaign:not([data-marker])")
        _assert_clean(console)


class TestTheAlert:
    def test_a_node_starts_the_mission_and_the_alert_takes_the_screen(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        page.click('.mission-node[data-mission-id="the_sweep"] button')
        page.wait_for_selector("#mission-alert")
        assert game.posts[0] == ("start", {})
        assert page.get_attribute("#tpanel-campaign", "data-stage") == "alert"
        assert not page.is_visible("#mission-campaign")
        assert page.evaluate("(document.activeElement || {}).id") == "mission-alert-title"
        _assert_clean(console)

    def test_the_alert_carries_its_line_brief_intel_card_exercise_and_data_note(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _alert(page, game)
        assert page.text_content(".mission-alert__line").strip() == game.alert["alert_line"]
        assert page.locator(".mission-alert__brief li").count() == 2
        intel = _INTEL["50321"]
        # Verbatim, with its source.
        assert page.text_content(".mission-intel__quote p").strip() == intel["significance"]
        assert page.text_content(".mission-intel__quote cite").strip() == intel["source"]
        assert page.text_content(".mission-threat").strip() == "CRITICAL"
        assert page.is_visible(".mission-alert .mission-exercise__badge")
        assert page.text_content(".mission-data-note").strip() == "Element sets: bundled, SYNTHETIC"
        assert page.text_content(".mission-first-action__text").strip() == game.alert["first_action"]
        # The klaxon runs a few times, then stops: never an endless flash.
        klaxon = page.eval_on_selector(".mission-klaxon", "e => getComputedStyle(e).animationIterationCount")
        assert klaxon == "4"
        _assert_clean(console)

    def test_without_an_inject_there_is_no_exercise_badge(self, console: Console) -> None:
        game = Game(console, alert=alert_context(exercise=False))
        page = _training(console, game)
        _alert(page, game)
        assert page.locator(".mission-alert .mission-exercise").count() == 0
        _assert_clean(console)

    def test_stand_down_abandons_and_brings_the_map_back(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _alert(page, game)
        page.click(".mission-alert button:has-text('Stand down')")
        page.wait_for_selector("#mission-alert", state="detached")
        assert game.posts[-1][0] == "abandon"
        assert page.is_visible("#mission-campaign .mission-campaign")
        assert page.get_attribute("#tpanel-campaign", "data-stage") == ""
        _assert_clean(console)


class TestTheHud:
    def test_take_the_watch_posts_nothing_and_docks_the_hud_beside_the_frame(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        assert [action for action, _ in game.posts] == ["start"]
        assert page.is_visible("#tpanel-console")
        assert page.get_attribute("#mission-hud", "data-mission-id") == _MISSION
        frame_box = page.locator("#training-console-frame").bounding_box()
        hud_box = page.locator("#mission-hud-wrap").bounding_box()
        assert frame_box["width"] > 800
        if page.is_visible("#mission-hud-handle"):   # below 1680 px: over the frame's right edge
            assert abs((frame_box["x"] + frame_box["width"]) - (hud_box["x"] + hud_box["width"])) < 4
        else:                                         # from 1680 px: beside it, outside the frame
            assert abs((frame_box["x"] + frame_box["width"]) - hud_box["x"]) < 4
        assert page.is_visible("#mission-hud .mission-exercise__badge")
        # The campaign tab says a mission is running, from the server, and takes the operator back to it.
        page.click("#tnav-campaign")
        page.wait_for_selector("#mission-resume")
        assert page.text_content("#mission-resume-title") == "The inspector"
        page.click("#mission-resume button")
        assert page.is_visible("#mission-hud")
        _assert_clean(console)

    def test_it_polls_every_two_seconds_and_on_training_changed(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        start = _gets(game)
        page.wait_for_timeout(4500)
        assert _gets(game) - start >= 2
        before = _gets(game)
        page.evaluate("htmx.trigger(document.body, 'training-changed')")
        page.wait_for_timeout(400)
        assert _gets(game) > before
        _assert_clean(console)

    def test_a_condition_met_ticks_with_a_points_burst_and_the_score(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.meet("screen")
        page.wait_for_selector('#mission-hud li[data-objective-id="screen"][data-status="met"]', timeout=5000)
        assert page.get_attribute('li[data-objective-id="screen"]', "data-just-met") == "true"
        assert page.locator("#mission-fx .mission-burst").text_content() == "+100"
        _until(page, "document.getElementById('mission-score-value').textContent === '100'")
        assert page.text_content("#mission-announce") == (
            "Objective met: Screen SKYNET 5A in Asset Screening. Plus 100 score.")
        page.wait_for_timeout(1600)
        assert page.locator(".mission-burst").count() == 0   # gone, and not fired again by the next poll
        _assert_clean(console)

    def test_a_request_in_the_console_frame_ticks_it_within_a_second(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        frame = _take_the_watch(page, game)
        _wait_for_poll(page, game)   # the next poll is now two seconds away
        game.meet("screen")
        started = time.monotonic()
        frame.locator("body").evaluate("() => htmx.ajax('GET', '/static/vendored.json', {target: 'body', swap: 'none'})")
        page.wait_for_selector('li[data-objective-id="screen"][data-status="met"]', timeout=5000)
        assert time.monotonic() - started < 1.0
        _assert_clean(console)

    def test_an_answer_posts_its_objective_and_value(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.fill("#mission-answer-range", "412")
        page.click("#mission-answer-submit-range")
        page.wait_for_selector('li[data-objective-id="range"][data-status="met"]')
        assert ("answer", {"objective_id": "range", "value": "412"}) in game.posts
        assert page.locator('form[name="mission-answer"]').count() == 0
        _assert_clean(console)

    def test_a_wrong_answer_shows_as_missed(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.fill("#mission-answer-range", "900")
        page.press("#mission-answer-range", "Enter")
        page.wait_for_selector('li[data-objective-id="range"][data-status="failed"]')
        assert "missed" in page.text_content('li[data-objective-id="range"]')
        _assert_clean(console)

    def test_a_choice_posts_its_objective_and_option(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.check("#mission-choice-move-west")
        page.click("#mission-choose-submit-move")
        page.wait_for_selector('li[data-objective-id="move"][data-status="met"]')
        assert ("choose", {"objective_id": "move", "option_id": "west"}) in game.posts
        _assert_clean(console)

    def test_what_is_typed_and_its_focus_survive_a_poll(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.click("#mission-answer-range")
        page.keyboard.type("41")
        _wait_for_poll(page, game)
        assert page.input_value("#mission-answer-range") == "41"
        assert page.evaluate("(document.activeElement || {}).id") == "mission-answer-range"
        page.keyboard.type("2")
        page.keyboard.press("Enter")
        page.wait_for_selector('li[data-objective-id="range"][data-status="met"]')
        _assert_clean(console)

    def test_the_clock_runs_against_par(self, console: Console) -> None:
        game = Game(console, started_at=(datetime.now(UTC) - timedelta(seconds=75)).isoformat())
        page = _training(console, game)
        _take_the_watch(page, game)
        assert page.text_content("#mission-clock-time") in {"1:15", "1:16", "1:17", "1:18"}
        first = page.text_content("#mission-clock-time")
        page.wait_for_timeout(1100)
        assert page.text_content("#mission-clock-time") != first
        assert page.get_attribute("#mission-clock", "data-over-par") == "false"
        _assert_clean(console)

    def test_past_par_the_clock_says_so(self, console: Console) -> None:
        game = Game(console, par_seconds=60)
        game.started_at = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
        page = _training(console, game)
        _take_the_watch(page, game)
        _until(page, "document.getElementById('mission-clock').dataset.overPar === 'true'", 3)
        _assert_clean(console)

    def test_a_reload_picks_the_running_mission_up_again(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.reload()
        # Back on the Campaign tab, as every arrival is, with the HUD fetched again behind the console.
        page.wait_for_selector("#mission-hud-dock #mission-hud", state="attached")
        page.wait_for_selector("#mission-resume")
        assert page.text_content("#mission-resume-title") == "The inspector"
        _assert_clean(console)


class TestTheHint:
    def test_a_hint_posts_shows_its_text_and_spotlights_the_control_in_the_frame(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        frame = _take_the_watch(page, game)
        page.click("#mission-hint-screen")
        page.wait_for_selector('li[data-objective-id="screen"] .mission-hint__text')
        assert ("hint", {"objective_id": "screen"}) in game.posts
        assert _HINTS["screen"][0] in page.text_content('li[data-objective-id="screen"]')
        ring = frame.locator(".mission-spotlight")
        ring.wait_for(state="visible")
        page.wait_for_timeout(300)
        r = ring.bounding_box()
        t = frame.locator(_SCREENING_TAB).bounding_box()
        assert r["x"] <= t["x"] and r["y"] <= t["y"]
        assert r["x"] + r["width"] >= t["x"] + t["width"] and r["y"] + r["height"] >= t["y"] + t["height"]
        # A poll that changes nothing keeps it; a click in the console takes it away.
        _wait_for_poll(page, game)
        assert ring.count() == 1
        frame.locator(_SCREENING_TAB).click()
        ring.wait_for(state="detached")
        # Show me draws it again; progress on the next HUD update takes it away. (At this 1280 px viewport the HUD
        # overlays the frame, and the click in the console folded it to its handle.)
        if page.is_visible("#mission-hud-handle") and page.get_attribute("#mission-hud-wrap", "data-collapsed") == "true":
            page.click("#mission-hud-handle")
        page.click("#mission-show-screen")
        ring.wait_for(state="visible")
        game.meet("range")
        ring.wait_for(state="detached", timeout=5000)
        _assert_clean(console)


class TestTheDebrief:
    def _finish(self, page: Any, game: Game) -> None:
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        _until(page, "document.activeElement && (document.activeElement || {}).id === 'mission-finish'", 3)
        page.keyboard.press("Enter")
        page.wait_for_selector("#mission-debrief")

    def test_all_met_focuses_finish_and_the_debrief_takes_the_hud_down(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        self._finish(page, game)
        assert game.posts[-1][0] == "finish"
        assert page.is_visible("#tpanel-campaign")
        assert page.get_attribute("#tpanel-campaign", "data-stage") == "debrief"
        assert page.inner_html("#mission-hud-dock") == ""
        assert page.is_hidden("#mission-hud-wrap")
        gets = _gets(game)
        page.wait_for_timeout(2500)
        assert _gets(game) == gets   # the HUD stopped asking
        _assert_clean(console)

    def test_the_stars_come_out_one_by_one_with_their_reasons(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        self._finish(page, game)
        revealed = "document.querySelectorAll('.mission-star-slot.is-revealed').length"
        assert page.evaluate(revealed) == 0
        _until(page, f"{revealed} === 1", 3)
        assert page.evaluate(revealed) == 1
        _until(page, f"{revealed} === 3", 4)
        assert page.get_attribute("#mission-debrief", "data-reveal") == "done"
        whys = page.locator(".mission-star-slot__why").all_text_contents()
        assert whys == [r["why"] for r in game.debrief["star_reasons"]]
        assert page.locator(".mission-star-slot.is-earned").count() == 2
        _until(page, "document.getElementById('mission-debrief-points').textContent === '375'", 3)
        assert "Observer" in page.text_content(".mission-promotion")
        assert page.text_content(".mission-best__text").strip() == game.debrief["best_answer_note"]
        _assert_clean(console)

    def test_next_mission_starts_it_and_back_returns_to_the_map(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        self._finish(page, game)
        page.click("#mission-next")
        page.wait_for_selector("#mission-alert")
        assert game.posts[-1][0] == "start"
        page.click("#mission-take-watch")
        page.wait_for_selector("#mission-hud")
        game.debrief = debrief_context(stars=0, rank_up=False)
        game.debrief["next_mission"] = None
        page.click("#mission-finish")   # not all met: it asks first, and the test accepts
        page.wait_for_selector("#mission-debrief")
        assert page.locator("#mission-next").count() == 0
        page.click("#mission-to-campaign")
        assert page.is_visible("#mission-campaign .mission-campaign")
        _assert_clean(console)

    def test_abandon_on_the_hud_returns_to_the_map(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.click("#mission-abandon")
        page.wait_for_selector("#mission-hud", state="detached")
        assert game.posts[-1][0] == "abandon"
        assert page.is_visible("#tpanel-campaign")
        assert page.evaluate("sessionStorage.getItem('spectre-mission-running')") is None
        _assert_clean(console)


class TestMotionSoundKeyboardAndContrast:
    def test_reduced_motion_shows_every_star_at_once_and_stops_the_animations(self, console: Console) -> None:
        console.page.emulate_media(reduced_motion="reduce")
        game = Game(console)
        page = _training(console, game)
        assert page.eval_on_selector('.mission-node[data-next="true"] .mission-node__disc',
                                     "e => getComputedStyle(e).animationName") == "none"
        _alert(page, game)
        assert page.eval_on_selector(".mission-klaxon", "e => getComputedStyle(e).animationName") == "none"
        page.click("#mission-take-watch")
        page.wait_for_selector("#mission-hud")
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        assert page.eval_on_selector('li[data-just-met="true"]', "e => getComputedStyle(e).animationName") == "none"
        page.click("#mission-finish")
        page.wait_for_selector("#mission-debrief")
        assert page.locator(".mission-star-slot.is-revealed").count() == 3
        assert page.text_content("#mission-debrief-points") == "375"
        _assert_clean(console)

    def test_sound_is_off_until_turned_on_then_tones_play(self, console: Console) -> None:
        console.page.context.add_init_script(_FAKE_AUDIO)
        game = Game(console)
        page = _training(console, game)
        assert page.get_attribute("#mission-sound-toggle", "aria-pressed") == "false"
        _take_the_watch(page, game)
        game.meet("screen")
        page.wait_for_selector('li[data-objective-id="screen"][data-status="met"]', timeout=5000)
        assert page.evaluate("window.__audioContexts") == 0   # nothing made a sound
        page.click("#mission-sound-toggle")
        assert page.get_attribute("#mission-sound-toggle", "aria-pressed") == "true"
        assert page.evaluate("localStorage.getItem('spectre-mission-sound')") == "on"
        page.evaluate("window.__tones = []")
        game.meet("range")
        _until(page, "window.__tones.length >= 2", 5)
        # The second objective met in a row, with no hint between: a combo, played a whole tone higher.
        assert page.evaluate("window.__tones") == [739.98, 1108.73]
        page.evaluate("window.__tones = []")
        game.meet("move")
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        page.click("#mission-finish")
        page.wait_for_selector("#mission-debrief")
        _until(page, "window.__tones.includes(1046.5)", 3)   # mission complete
        page.click("#mission-sound-toggle")
        assert page.evaluate("localStorage.getItem('spectre-mission-sound')") is None
        _assert_clean(console)

    def test_the_mission_is_flown_from_the_keyboard(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        for _ in range(60):
            page.keyboard.press("Tab")
            if page.evaluate("!!document.activeElement.closest('.mission-node[data-mission-id=\"the_sweep\"]')"):
                break
        else:
            raise AssertionError("Tab never reached the next mission")
        page.keyboard.press("Enter")
        page.wait_for_selector("#mission-alert")
        page.focus("#mission-take-watch")
        page.keyboard.press("Enter")
        page.wait_for_selector("#mission-hud")
        page.focus("#mission-choice-move-east")
        page.keyboard.press("ArrowDown")   # to west
        assert page.is_checked("#mission-choice-move-west")
        page.keyboard.press("Enter")       # submits its form
        page.wait_for_selector('li[data-objective-id="move"][data-status="met"]')
        _assert_clean(console)

    def test_text_meets_wcag_aa_contrast_on_every_screen(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        selectors = {
            "campaign": [".mission-eyebrow", ".mission-campaign__title", ".mission-campaign__tag",
                         ".mission-rank__title", ".mission-rank__points", ".mission-rank__conditions li",
                         ".mission-chapter__title", ".mission-chapter__blurb", ".mission-node__title",
                         ".mission-node__meta", ".mission-node__lock", ".mission-node__teaser", ".mission-badge",
                         ".mission-node__disc"],
            "alert": [".mission-alert__title", ".mission-alert__line", ".mission-alert__brief li",
                      ".mission-alert__flag", ".mission-exercise__badge", ".mission-exercise__text",
                      ".mission-first-action__text", ".mission-intel__facts dt", ".mission-intel__facts dd",
                      ".mission-threat", ".mission-intel__quote p", ".mission-intel__quote footer",
                      ".mission-data-note", "#mission-take-watch"],
            "hud": [".mission-hud__title", ".mission-gauge__label", ".mission-gauge__value", ".mission-gauge__sub",
                    ".mission-progress__label", ".mission-objective__text", ".mission-objective__points",
                    ".mission-answer__label", ".mission-choice__option", "#mission-finish",
                    ".mission-btn--hint", "#mission-abandon", ".mission-sound"],
            "debrief": [".mission-debrief__title", ".mission-star-slot__state", ".mission-star-slot__why",
                        ".mission-stat dt", ".mission-stat dd", ".mission-best__text", ".mission-unlocked__list li",
                        ".mission-promotion__title", ".mission-more summary", "#mission-next"],
        }
        failures: list[Any] = []

        def check(screen: str) -> None:
            found = page.evaluate(_CONTRAST, selectors[screen])
            assert found, screen
            failures.extend((screen, f) for f in found if f["ratio"] < f["floor"])

        check("campaign")
        _alert(page, game)
        page.wait_for_timeout(1200)   # past the klaxon's flash
        check("alert")
        page.click("#mission-take-watch")
        page.wait_for_selector("#mission-hud")
        check("hud")
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        page.click("#mission-finish")
        page.wait_for_selector("#mission-debrief[data-reveal='done']", timeout=5000)
        page.wait_for_timeout(800)
        check("debrief")
        assert failures == []
        _assert_clean(console)


# ── The 0.48 shell review: errors, widths, focus, rewards and the fun ───────────


def _hud_open(page: Any) -> None:
    """Wait until a HUD response has landed and its init has run."""
    page.wait_for_selector("#mission-hud-dock #mission-hud", state="attached")
    page.wait_for_timeout(250)


#: Whether the control *sel* inside the console frame is the topmost thing at its centre, on the training page.
_REACHABLE = """([sel]) => { const f = document.getElementById('training-console-frame'); const fr = f.getBoundingClientRect();
  const el = f.contentDocument.querySelector(sel); if (!el) return 'missing';
  const r = el.getBoundingClientRect(); if (!r.width) return 'hidden';
  const top = document.elementFromPoint(fr.left + r.left + r.width / 2, fr.top + r.top + r.height / 2);
  return top === f ? 'ok' : 'covered by ' + (top && (top.id || top.className));
}"""

#: Every console control a Chapter 1 or 2 mission names, by the tab that shows it.
_NAMED: dict[str | None, list[str]] = {
    None: ["button.stab[data-panel='sb-assets']", "button.atab[data-panel='at-blue']",
           "button.atab[data-panel='at-red']", "button.htab[data-panel='hero-sweep']",
           "button.htab[data-panel='hero-screen']", "button.htab[data-panel='hero-engine']", "#ts-red-sat"],
    "button.htab[data-panel='hero-screen']": ["#scr-asset"],
    "button.htab[data-panel='hero-engine']": ["#ie-red-sat", "#ie-blue-sat", "#ie-manoeuvring",
                                              "#intercept-engine-form button[type=submit]"],
}

#: The conftest's own page probes, recorded before any script runs (a policy violation, the splash already seen).
_PROBES = (
    "window.__spectreViolations = [];"
    "document.addEventListener('securitypolicyviolation', function (e) {"
    "  window.__spectreViolations.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline'));"
    "});"
    "try { sessionStorage.setItem('spectre-splash-seen', '1'); } catch (e) {}"
)


def _wide_console(browser: Browser, width: int) -> tuple[Any, Console]:
    context = browser.browser.new_context(storage_state=browser.signed_in, viewport={"width": width, "height": 900})
    context.add_init_script(_PROBES)
    page = context.new_page()
    console = Console(page, browser.base_url)
    page.on("pageerror", lambda exc: console.errors.append(f"uncaught: {exc}"))
    page.on("console", lambda msg: console.errors.append(f"console: {msg.text}") if msg.type == "error" else None)
    page.on("dialog", lambda dialog: dialog.accept())
    return context, console


def _unreachable(page: Any, frame: Any) -> list[str]:
    found = []
    for opener, selectors in _NAMED.items():
        if opener:
            frame.locator(opener).click()
            page.wait_for_timeout(200)
        for selector in selectors:
            result = page.evaluate(_REACHABLE, [selector])
            if result != "ok":
                found.append(f"{selector}: {result}")
    frame.locator("button.htab[data-panel='hero-sweep']").click()
    return found


_DOUBLE_CLICK = """() => { const b = document.getElementById('mission-answer-submit-range');
  b.click(); const d = b.disabled; b.click(); return d; }"""


class TestErrorsShowInPlace:
    """B1: an error response must never take the HUD down for good."""

    def test_a_non_number_answer_shows_its_error_in_the_hud(self, console: Console) -> None:
        """The 422's error shows in place, with a poll in flight across it, and stays through later polls until the
        operator types in that answer again."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.holding.add("hud")
        _held(page, game, "hud")                # a poll in flight across the post
        page.fill("#mission-answer-range", "79.72° E at scenario time")
        page.click("#mission-answer-submit-range")
        page.wait_for_selector("#mission-hud-error")
        game.release("hud")                     # the late poll: stale, dropped, the error stands
        page.wait_for_timeout(500)
        assert page.get_attribute("#mission-hud-error", "role") == "alert"
        assert page.text_content("#mission-hud-error").strip() == "Give a number in km."
        assert page.get_attribute('li[data-objective-id="range"]', "data-status") == "open"
        assert page.evaluate("(document.activeElement || {}).id") == "mission-answer-range"
        _wait_for_poll(page, game)
        _wait_for_poll(page, game)              # two fresh polls, neither carrying the error: it is kept
        assert page.text_content("#mission-hud-error").strip() == "Give a number in km."
        page.focus("#mission-answer-range")
        page.keyboard.press("End")
        page.keyboard.type("1")                 # the operator acts on it again: the error goes
        assert page.locator("#mission-hud-error").count() == 0
        _wait_for_poll(page, game)
        assert page.locator("#mission-hud-error").count() == 0
        page.fill("#mission-answer-range", "412")
        page.press("#mission-answer-range", "Enter")
        page.wait_for_selector('li[data-objective-id="range"][data-status="met"]')
        assert page.locator("#mission-hud-error").count() == 0
        _assert_clean(console, 422)

    def test_a_double_click_under_latency_sends_one_answer(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.fill("#mission-answer-range", "412")
        # Two clicks in one task, as a double click lands before any response could.
        disabled = page.evaluate(_DOUBLE_CLICK)
        assert disabled
        page.wait_for_selector('li[data-objective-id="range"][data-status="met"]')
        page.wait_for_timeout(300)
        assert [a for a, _ in game.posts].count("answer") == 1
        assert page.locator("#mission-finish[hx-disabled-elt='this']").count() == 1
        _assert_clean(console)

    def test_a_mission_no_longer_running_says_so_and_goes_back(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.refuse["hud"] = 409
        game.reasons["hud"] = "This mission is not running: start it from the campaign."
        page.wait_for_selector(".mission-hud__ended", timeout=5000)
        # The server's own reason (review item 8), shown and said.
        assert page.text_content(".mission-hud__ended p").strip() == game.reasons["hud"]
        assert page.text_content("#mission-announce") == game.reasons["hud"]
        assert page.locator("#mission-hud").count() == 0
        page.click("#mission-ended-back")
        assert page.is_visible("#tpanel-campaign")
        assert page.is_hidden("#mission-hud-wrap")
        _assert_clean(console, 409)

    def test_a_server_fault_on_a_poll_keeps_the_hud(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.refuse["hud"] = 500
        page.wait_for_timeout(2600)
        assert page.locator("#mission-hud").count() == 1
        del game.refuse["hud"]
        game.meet("screen")
        page.wait_for_selector('li[data-objective-id="screen"][data-status="met"]', timeout=5000)
        assert all("500" in p for p in console.problems())

    def test_a_refused_start_shows_the_reason(self, console: Console) -> None:
        """S1: a locked (403) or refused (409) start lands the server's reason where the alert would."""
        for code in (403, 409):
            game = Game(console, refuse={"start": code})
            page = _training(console, game)
            page.click('.mission-node[data-mission-id="the_sweep"] button')
            page.wait_for_selector("#mission-stage .error-msg")
            assert "Earn a star" in page.text_content("#mission-stage")
            assert page.is_visible("#mission-campaign .mission-campaign")
            console.page.unroute("**/training/m/**")
        _assert_clean(console, 403, 409)

    def test_an_expired_sign_in_shows_a_message_not_the_login_page(self, console: Console) -> None:
        """S8: a 401, or an HX-Redirect to the login page, ends the HUD with a message and a link."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.refuse["hud"] = 401
        page.wait_for_selector("#mission-session-ended", state="visible", timeout=5000)
        assert page.locator("#mission-hud-dock form").count() == 0
        assert page.get_attribute("#mission-session-ended a", "href") == "/login"
        _assert_clean(console, 401)

    def test_an_hx_redirect_to_login_does_not_leave_the_page(self, console: Console) -> None:
        game = Game(console, headers={"hud": {"HX-Redirect": "/login"}})
        page = _training(console, game)
        _alert(page, game)
        page.click("#mission-take-watch")
        page.wait_for_selector("#mission-session-ended", state="visible", timeout=5000)
        assert page.url.endswith("/training")
        _assert_clean(console)


class TestTheHudAtEveryWidth:
    """B2: the console keeps its own layout, sidebar and all, beside or under the HUD."""

    def _check(self, browser: Browser, width: int) -> None:
        context, console = _wide_console(browser, width)
        try:
            game = Game(console)
            page = _training(console, game)
            frame = _take_the_watch(page, game)
            page.wait_for_timeout(500)
            frame_width = page.evaluate("document.getElementById('training-console-frame').offsetWidth")
            assert frame_width > 800, (width, frame_width)   # above the console's 768 px drawer breakpoint
            assert frame.locator("#sidebar").evaluate("e => getComputedStyle(e).transform") == "none"
            overlay = width < 1680
            assert overlay or frame_width >= 980   # docked, the console's 962 px layout fits unclipped
            position = page.eval_on_selector("#mission-hud-wrap", "e => getComputedStyle(e).position")
            assert position == ("absolute" if overlay else "relative")
            assert page.is_visible("#mission-hud-handle") == overlay
            if overlay:
                self._overlay(page, frame, game)
            else:
                assert _unreachable(page, frame) == []
            _assert_clean(console)
        finally:
            context.close()

    def _overlay(self, page: Any, frame: Any, game: Game) -> None:
        # Expanded over the frame: the sidebar is in reach, and working in the console folds the HUD away.
        assert page.evaluate(_REACHABLE, ["button.stab[data-panel='sb-assets']"]) == "ok"
        frame.locator("button.stab[data-panel='sb-assets']").click()
        assert page.get_attribute("#mission-hud-wrap", "data-collapsed") == "true"
        page.wait_for_timeout(400)
        assert _unreachable(page, frame) == []
        # The handle brings it back; collapsed again, the choice holds across a reload.
        page.click("#mission-hud-handle")
        assert page.get_attribute("#mission-hud-handle", "aria-expanded") == "true"
        page.click("#mission-hud-handle")
        assert page.get_attribute("#mission-hud-handle", "aria-expanded") == "false"
        page.reload()
        page.click("#tnav-console")
        _hud_open(page)
        assert page.get_attribute("#mission-hud-wrap", "data-collapsed") == "true"
        # An objective met peeks it open for a moment.
        game.meet("screen")
        _until(page, "document.getElementById('mission-hud-wrap').dataset.peek === 'true'", 6)
        _until(page, "!document.getElementById('mission-hud-wrap').dataset.peek", 5)

    def test_at_1280(self, browser: Browser) -> None:
        self._check(browser, 1280)

    def test_at_1366(self, browser: Browser) -> None:
        self._check(browser, 1366)

    def test_at_1440(self, browser: Browser) -> None:
        self._check(browser, 1440)

    def test_at_1600(self, browser: Browser) -> None:
        self._check(browser, 1600)

    def test_at_1920(self, browser: Browser) -> None:
        self._check(browser, 1920)


class TestRunningAndFocus:
    def test_starting_another_mission_asks_first(self, console: Console) -> None:
        """S2: the strip comes from the server, and a start that would end the running mission confirms."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.click("#tnav-campaign")
        page.wait_for_selector("#mission-resume")
        node = page.locator('.mission-node[data-mission-id="the_sweep"] button')
        assert node.get_attribute("hx-confirm") == "The inspector is still running. End it and start The sweep?"
        page.evaluate("window.confirm = (m) => { window.__asked = m; return false; }")   # the operator says no
        node.click()
        page.wait_for_timeout(500)
        assert page.evaluate("window.__asked") == node.get_attribute("hx-confirm")
        assert [a for a, _ in game.posts].count("start") == 1
        _assert_clean(console)

    def test_focus_follows_the_work(self, console: Console) -> None:
        """S3: the HUD heading on Take the watch; the next open field after each post; Debrief when none is left.

        Flown on a CPU slowed fourfold, as on a loaded machine, where a poll is still in flight when each post goes:
        nothing may be aborted (htmx would log it as a console error) and focus must still land."""
        game = Game(console)
        page = _training(console, game)
        console.page.context.new_cdp_session(page).send("Emulation.setCPUThrottlingRate", {"rate": 4})
        _take_the_watch(page, game)
        _until(page, "(document.activeElement || {}).id === 'mission-hud-title'", 3)
        page.click("#mission-hint-range")
        _until(page, "(document.activeElement || {}).id === 'mission-answer-range'", 3)
        page.keyboard.type("412")
        page.keyboard.press("Enter")
        _until(page, "((document.activeElement || {}).id || '').startsWith('mission-choice-move-')", 3)
        game.meet("screen")
        page.check("#mission-choice-move-west")
        page.click("#mission-choose-submit-move")
        _until(page, "(document.activeElement || {}).id === 'mission-finish'", 3)
        _assert_clean(console)

    def test_stand_down_returns_focus_to_the_node(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        page.click('.mission-node[data-mission-id="the_sweep"] button')
        page.wait_for_selector("#mission-alert")
        page.click(".mission-alert button:has-text('Stand down')")
        _until(page, "!!document.activeElement.closest('.mission-node[data-mission-id=\"inspector\"]')", 3)
        _assert_clean(console)

    def test_a_miss_is_announced_and_debrief_needs_no_confirm(self, console: Console) -> None:
        """S4, and the fifth fun item: a missed number says Close or Way off, never the answer."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.fill("#mission-answer-range", "440")
        page.press("#mission-answer-range", "Enter")
        page.wait_for_selector('li[data-objective-id="range"][data-status="failed"]')
        _until(page, "document.getElementById('mission-announce').textContent === 'Missed: Range at closest approach.'", 3)
        assert page.text_content('li[data-objective-id="range"] .mission-miss').strip() == "Close"
        assert "412" not in page.text_content("#mission-hud")
        game.meet("screen")
        game.meet("move")
        page.wait_for_selector('#mission-hud[data-open="0"]', timeout=5000)
        assert page.get_attribute("#mission-finish", "hx-confirm") is None
        assert page.text_content("#mission-finish").strip() == "Debrief"
        _assert_clean(console)

    def test_a_hint_shows_its_cost_and_the_score_drops_at_once(self, console: Console) -> None:
        """S5: the reward shown is the reward scored."""
        game = Game(console)
        game.meet("screen")
        page = _training(console, game)
        _take_the_watch(page, game)
        assert page.text_content("#mission-hint-range .mission-btn__cost").strip() == "(-25)"
        assert "costs 25 score" in page.text_content("#mission-hint-range")
        page.click("#mission-hint-range")
        page.wait_for_selector('li[data-objective-id="range"] .mission-hint__text')
        assert page.text_content("#mission-score-value") == "75"
        assert page.locator(".mission-burst--cost").text_content() == "-25"
        _assert_clean(console)

    def test_reduced_motion_keeps_the_reward_as_a_still_chip(self, console: Console) -> None:
        """S6."""
        console.page.emulate_media(reduced_motion="reduce")
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.meet("screen")
        page.wait_for_selector(".mission-burst.is-still", timeout=5000)
        chip = page.locator(".mission-burst--gain")
        assert chip.text_content() == "+100"
        assert chip.is_visible()
        assert chip.evaluate("e => getComputedStyle(e).animationName") == "none"
        _assert_clean(console)


class TestTheSpotlightFallsBack:
    """S7: a hidden target rings the control that would show it, and the page itself never scrolls."""

    def _show(self, page: Any, game: Game, selector: str) -> None:
        game.objective("range")["hint_text"], game.objective("range")["spotlight"] = "Look here.", selector
        game.hints_used = 1
        _wait_for_poll(page, game)

    def test_a_target_in_a_hidden_tab_rings_its_tab(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        frame = _take_the_watch(page, game)
        before = page.evaluate("[scrollY, document.getElementById('training-main').scrollTop]")
        self._show(page, game, "#scr-asset")
        ring = frame.locator(".mission-spotlight")
        ring.wait_for(state="visible")
        assert ring.get_attribute("data-say") == "Open Asset Screening first"
        assert page.text_content("#mission-announce") == "Open Asset Screening first."
        page.wait_for_timeout(300)
        r, t = ring.bounding_box(), frame.locator(_SCREENING_TAB).bounding_box()
        assert r["x"] <= t["x"]
        assert r["x"] + r["width"] >= t["x"] + t["width"]
        page.click("#mission-show-range")
        page.wait_for_timeout(400)
        assert page.evaluate("[scrollY, document.getElementById('training-main').scrollTop]") == before
        _assert_clean(console)

    def test_a_target_in_a_closed_details_rings_its_summary(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        frame = _take_the_watch(page, game)
        self._show(page, game, "#ts-manual-red-tle")
        ring = frame.locator(".mission-spotlight")
        ring.wait_for(state="visible")
        assert ring.get_attribute("data-say") == "Open Manual Red TLE Override first"
        _assert_clean(console)

    def test_nothing_to_ring_draws_nothing_and_runs_no_loop(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        frame = _take_the_watch(page, game)
        self._show(page, game, "#no-such-control")
        assert frame.locator(".mission-spotlight").count() == 0
        assert page.text_content("#mission-announce") == "That control is not on the console page yet."
        _assert_clean(console)


class TestTheNits:
    def test_each_control_has_its_own_name_and_the_toggle_says_its_state_once(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        names = page.eval_on_selector_all(
            "#mission-hud button", "bs => bs.map(b => b.textContent.replace(/\\s+/g, ' ').trim())")
        assert len(names) == len(set(names)), names
        assert page.locator("#mission-hud legend").count() == 0
        assert page.get_attribute(".mission-choice", "aria-labelledby") == "mission-objective-move-text"
        assert page.get_attribute("#mission-sound-toggle .mission-sound__state", "aria-hidden") == "true"
        _assert_clean(console)

    def test_polling_rests_while_unseen_and_asks_at_once_when_shown(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.click("#tnav-campaign")
        page.wait_for_timeout(300)
        quiet = _gets(game)
        page.wait_for_timeout(2600)
        assert _gets(game) == quiet   # the Console tab is not showing
        page.click("#tnav-console")
        page.wait_for_timeout(600)
        assert _gets(game) > quiet
        page.evaluate("Object.defineProperty(document, 'hidden', {value: true, configurable: true})")
        page.wait_for_timeout(300)
        hidden = _gets(game)
        page.wait_for_timeout(2600)
        assert _gets(game) == hidden  # the browser tab is hidden
        page.evaluate("""() => { Object.defineProperty(document, 'hidden', {value: false, configurable: true});
                                 document.dispatchEvent(new Event('visibilitychange')); }""")
        page.wait_for_timeout(600)
        assert _gets(game) > hidden
        _assert_clean(console)

    def test_a_hidden_campaign_is_fetched_when_shown_not_on_every_change(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        page.wait_for_timeout(500)
        fetched: list[str] = []
        page.on("request", lambda r: fetched.append(r.url) if r.url.endswith("/training/m/campaign") else None)
        page.evaluate("htmx.trigger(document.body, 'training-changed')")
        page.evaluate("htmx.trigger(document.body, 'training-changed')")
        page.wait_for_timeout(500)
        assert fetched == []
        page.click("#tnav-campaign")
        page.wait_for_timeout(500)
        assert len(fetched) == 1
        _assert_clean(console)


class TestTheFun:
    def test_back_to_back_objectives_make_a_combo_each_tone_higher(self, console: Console) -> None:
        console.page.context.add_init_script(_FAKE_AUDIO)
        console.page.context.add_init_script("try { localStorage.setItem('spectre-mission-sound', 'on'); } catch (e) {}")
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.meet("screen")
        page.wait_for_selector('li[data-objective-id="screen"][data-status="met"]', timeout=5000)
        first = page.evaluate("window.__tones.slice(-2)")
        game.meet("move")
        page.wait_for_selector(".mission-burst--combo", timeout=5000)
        assert page.text_content(".mission-burst--combo") == "Combo x2"
        second = page.evaluate("window.__tones.slice(-2)")
        assert second[0] > first[0]
        assert second[1] > first[1]
        _assert_clean(console)

    def test_the_clock_ring_marks_your_best_time(self, console: Console) -> None:
        game = Game(console, best_seconds=180)
        page = _training(console, game)
        _take_the_watch(page, game)
        assert page.get_attribute(".mission-clock__ghost", "stroke-dashoffset") == "-49.25"
        assert "Best 3:00" in page.text_content("#mission-clock")
        _assert_clean(console)

    def test_take_the_watch_flashes_on_watch(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _alert(page, game)
        page.click("#mission-take-watch")
        page.wait_for_selector("#mission-on-watch", state="visible", timeout=3000)
        page.wait_for_selector("#mission-on-watch", state="hidden", timeout=3000)
        _assert_clean(console)

    def test_stars_fly_home_and_a_new_best_is_stamped(self, console: Console) -> None:
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        page.click("#mission-finish")
        page.wait_for_selector("#mission-debrief[data-reveal='done']", timeout=5000)
        page.click("#mission-to-campaign")
        page.wait_for_selector(".mission-flying-star", state="attached", timeout=2000)
        assert page.locator(".mission-flying-star").count() == 2
        page.wait_for_selector('.mission-node[data-mission-id="inspector"] .mission-node__stamp', timeout=3000)
        assert page.text_content(".mission-node__stamp") == "New best"
        page.wait_for_selector(".mission-flying-star", state="detached", timeout=3000)
        _assert_clean(console)


# ── The final play-through's items ──────────────────────────────────────────────

#: Whether the element focused inside the console frame is the topmost thing at its centre, on the training page.
_FOCUSED_REACHABLE = """() => { const f = document.getElementById('training-console-frame'); const fr = f.getBoundingClientRect();
  const el = f.contentDocument.activeElement; if (!el || el === f.contentDocument.body) return 'body';
  const r = el.getBoundingClientRect(); if (!r.width || !r.height) return 'ok';
  const x = fr.left + r.left + r.width / 2, y = fr.top + r.top + r.height / 2;
  if (x < fr.left || x > fr.right || y < fr.top || y > fr.bottom) return 'ok';
  const top = document.elementFromPoint(x, y);
  return top === f ? 'ok' : (el.id || el.className || el.tagName) + ' covered by ' + (top && (top.id || top.className));
}"""


class TestTheFinalPlayThrough:
    def test_two_currencies_are_named_apart(self, console: Console) -> None:
        """1: the mission's figure is Score; the debrief adds the rank points this run paid, and why none."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        assert page.text_content("#mission-hud .mission-score .mission-gauge__label").strip() == "Score"
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        game.debrief["rank_points_earned"], game.debrief["rank_note"] = 0, "Replays pay no rank points"
        page.click("#mission-finish")
        page.wait_for_selector("#mission-debrief")
        assert page.text_content(".mission-stat--points dt").strip() == "Score"
        assert page.text_content(".mission-rank-points__figure").strip() == "+0 rank points"
        assert page.text_content(".mission-rank-points__note").strip() == "Replays pay no rank points"
        _assert_clean(console)

    def test_the_tagline_claims_computed_geometry_and_the_data_note_stands_out(self, console: Console) -> None:
        """2."""
        game = Game(console)
        page = _training(console, game)
        assert page.text_content(".mission-campaign__tag").strip() == "Real satellites. Computed geometry. Your watch."
        _alert(page, game)
        size = page.eval_on_selector(".mission-data-note", "e => parseFloat(getComputedStyle(e).fontSize)")
        assert size >= 16
        _assert_clean(console)

    def test_tabbing_in_the_console_folds_the_hud_and_never_stops_under_it(self, browser: Browser) -> None:
        """3: at 1366 px, keyboard into the console folds the overlaid HUD; no focused control is covered."""
        context, console = _wide_console(browser, 1366)
        try:
            game = Game(console)
            page = _training(console, game)
            frame = _take_the_watch(page, game)
            assert page.get_attribute("#mission-hud-wrap", "data-collapsed") == "false"
            frame.locator("button.stab[data-panel='sb-assets']").focus()
            assert page.get_attribute("#mission-hud-wrap", "data-collapsed") == "true"
            page.wait_for_timeout(400)
            covered = []
            for _ in range(60):
                page.keyboard.press("Tab")
                found = page.evaluate(_FOCUSED_REACHABLE)
                if found not in ("ok", "body"):
                    covered.append(found)
            assert covered == []
            _assert_clean(console)
        finally:
            context.close()

    def test_back_to_the_campaign_focuses_the_next_mission(self, console: Console) -> None:
        """4: the next mission's node, or the one just flown when there is none."""
        for following, expect in ((True, _NEXT), (False, _MISSION)):
            game = Game(console)
            if not following:
                game.debrief["next_mission"] = None
            page = _training(console, game)
            _take_the_watch(page, game)
            game.meet_all()
            page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
            page.click("#mission-finish")
            page.wait_for_selector("#mission-debrief[data-reveal='done']", timeout=6000)
            page.click("#mission-to-campaign")
            _until(page, f"!!document.activeElement.closest('.mission-node[data-mission-id=\"{expect}\"]')", 4)
            console.page.unroute("**/training/m/**")
            page.evaluate("sessionStorage.clear()")
        _assert_clean(console)

    def test_show_me_says_in_the_hud_what_it_cannot_show(self, console: Console) -> None:
        """5: a visible note under the hint, kept across polls, beside the live region."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.objective("range")["hint_text"], game.objective("range")["spotlight"] = "Look here.", "#no-such-control"
        game.hints_used = 1
        page.wait_for_selector('li[data-objective-id="range"] .mission-hint__note', timeout=5000)
        assert page.text_content('li[data-objective-id="range"] .mission-hint__note') == "Not on screen yet"
        _wait_for_poll(page, game)
        assert page.text_content('li[data-objective-id="range"] .mission-hint__note') == "Not on screen yet"
        game.objective("range")["spotlight"] = "#scr-asset"
        _wait_for_poll(page, game)
        if page.get_attribute("#mission-hud-wrap", "data-collapsed") == "true":
            page.click("#mission-hud-handle")
        page.click("#mission-show-range")
        _until(page, "document.querySelector('li[data-objective-id=\"range\"] .mission-hint__note')"
                     ".textContent === 'Open Asset Screening first'", 3)
        _assert_clean(console)

    def test_a_fault_or_a_lost_connection_says_so_and_keeps_the_answer(self, console: Console) -> None:
        """6: 5xx, 403 and a network failure each leave an alert line, the typed answer and a live button."""
        for code in (500, 403, 0):
            game = Game(console)
            page = _training(console, game)
            _take_the_watch(page, game)
            if code:
                game.refuse["answer"] = code
            else:
                page.route("**/training/m/*/answer", lambda route: route.abort())
            page.fill("#mission-answer-range", "41")
            page.click("#mission-answer-submit-range")
            page.wait_for_selector("#mission-hud-error", timeout=5000)
            assert page.text_content("#mission-hud-error") == "Could not reach the server. Try again."
            assert page.input_value("#mission-answer-range") == "41"
            _until(page, "!document.getElementById('mission-answer-submit-range').disabled", 3)
            console.page.unroute("**/training/m/*/answer")
            console.page.unroute("**/training/m/**")
            page.evaluate("sessionStorage.clear()")
        # Chromium logs each failed load, and htmx logs a send error and its afterRequest: nothing else.
        expected = ("status of 500", "status of 403", "net::ERR_FAILED", "htmx:sendError", "htmx:afterRequest")
        assert all(any(s in p for s in expected) for p in console.problems()), console.problems()

    def test_a_lost_star_offers_a_restart(self, console: Console) -> None:
        """7."""
        game = Game(console, star_lost=True)
        page = _training(console, game)
        _take_the_watch(page, game)
        assert page.text_content(".mission-star-lost__text").strip() == "A miss costs the stars on this run"
        assert page.get_attribute("#mission-restart", "hx-confirm")
        page.click("#mission-restart")
        page.wait_for_selector("#mission-alert")
        assert game.posts[-1][0] == "restart"
        assert page.is_visible("#tpanel-campaign")
        _assert_clean(console)

    def test_the_last_mission_of_a_chapter_gets_its_moment(self, console: Console) -> None:
        """9: Chapter complete with the chapter's stars, and why the next chapter is still locked."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        page.click("#mission-finish")
        page.wait_for_selector("#mission-chapter-complete")
        assert page.text_content(".mission-chapter-done__title").strip() == "Shadows in the Belt"
        assert page.text_content(".mission-chapter-done__stars").split()[0] == "7/9"
        assert "Reach Planner: 3 challenge passes." in page.text_content(".mission-chapter-done__next")

    def test_without_the_servers_word_the_map_finds_the_chapters_end(self, console: Console) -> None:
        """9, from the campaign map: the inspector closes no chapter, the listener closes Shadows in the Belt."""
        game = Game(console)
        game.debrief["chapter_complete"] = None
        page = _training(console, game)
        _take_the_watch(page, game)
        game.meet_all()
        page.wait_for_selector("#mission-hud.is-all-met", timeout=5000)
        page.click("#mission-finish")
        page.wait_for_selector("#mission-debrief")
        assert page.locator("#mission-chapter-complete").count() == 0    # not the chapter's last mission
        page.evaluate("""() => { const debrief = document.getElementById('mission-debrief');
          debrief.remove(); }""")
        game.debrief["mission"] = {"id": _NEXT, "title": "The listener"}
        page.evaluate("htmx.ajax('POST', '/training/m/listener/finish', {target: '#mission-stage', swap: 'innerHTML'})")
        page.wait_for_selector("#mission-chapter-complete")
        # The map's stars for the chapter (0 + 0 + 0) with this run's 2 on the listener.
        assert page.text_content(".mission-chapter-done__stars").strip() == "2/9 stars"
        assert "Shadows in the Belt" in page.text_content("#mission-chapter-complete")
        assert "Reach Planner" in page.text_content("#mission-chapter-complete")
        _assert_clean(console)
        _assert_clean(console)


class TestTheFinalNits:
    def test_a_title_that_asks_is_not_asked_twice(self, console: Console) -> None:
        game = Game(console)
        game.running = {"id": _MISSION, "title": "The inspector"}
        page = _training(console, game)
        confirm = page.get_attribute('.mission-node[data-mission-id="who_is_near"] button', "hx-confirm")
        assert confirm == "The inspector is still running. End it and start Who is near?"
        _assert_clean(console)

    def test_objective_met_and_all_met_are_both_said(self, console: Console) -> None:
        game = Game(console)
        game.meet("screen")
        game.meet("move")
        page = _training(console, game)
        _take_the_watch(page, game)
        page.wait_for_timeout(300)
        game.meet("range")
        _until(page, "document.getElementById('mission-announce').textContent.includes('All objectives met')", 5)
        said = page.text_content("#mission-announce")
        assert said.startswith("Objective met: Range at closest approach. Plus 150 score.")
        _assert_clean(console)

    def test_the_handle_keeps_clear_of_the_console_header(self, browser: Browser) -> None:
        context, console = _wide_console(browser, 1366)
        try:
            game = Game(console)
            page = _training(console, game)
            _take_the_watch(page, game)
            page.click("#mission-hud-handle")   # folded: the handle alone sits over the frame
            page.wait_for_timeout(400)
            assert page.evaluate(_REACHABLE, ["button.btn-logout"]) == "ok"
            _assert_clean(console)
        finally:
            context.close()


def _held(page: Any, game: Game, action: str) -> None:
    deadline = time.monotonic() + 5
    while not any(a == action for _, a in game.held):
        assert time.monotonic() < deadline, f"no {action} request went out"
        page.wait_for_timeout(50)


class TestNoRequestIsAborted:
    def test_a_post_while_a_poll_is_in_flight_aborts_nothing(self, console: Console) -> None:
        """Under load a poll is still in flight when the operator answers: nothing is aborted (htmx would log it as
        an error), the answer lands, and the late poll changes nothing."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.holding.add("hud")
        _held(page, game, "hud")
        page.fill("#mission-answer-range", "412")
        page.click("#mission-answer-submit-range")
        page.wait_for_selector('li[data-objective-id="range"][data-status="met"]')
        page.wait_for_timeout(2500)          # a poll would be due: none goes out while one is still in flight
        assert len(game.held) == 1
        game.release("hud")
        page.wait_for_timeout(600)
        assert page.get_attribute('li[data-objective-id="range"]', "data-status") == "met"
        _assert_clean(console)

    def test_a_poll_answered_first_still_lets_the_post_land(self, console: Console) -> None:
        """A poll out before the post answers before it and replaces the HUD: the post's answer lands on the new one."""
        game = Game(console)
        page = _training(console, game)
        _take_the_watch(page, game)
        game.holding.add("hud")
        _held(page, game, "hud")
        game.holding.add("answer")
        page.fill("#mission-answer-range", "412")
        page.click("#mission-answer-submit-range")
        _held(page, game, "answer")
        game.release("hud")
        page.wait_for_timeout(400)
        game.release("answer")
        page.wait_for_selector('li[data-objective-id="range"][data-status="met"]', timeout=5000)
        page.wait_for_timeout(800)
        assert page.locator("#mission-hud").count() == 1
        assert page.get_attribute('li[data-objective-id="range"]', "data-status") == "met"
        _assert_clean(console)
