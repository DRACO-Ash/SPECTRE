"""Every form field the operator types into has a label tied to it by id.

The 0.6.3 App Store scan flagged 9 fields with no associated label
(Web:InputWithoutLabelCheck): the SATNO boxes, the HRR search, the data mode
and TLE source selects, the UDL login, and the shared TLE name and text
fields. A placeholder or title is not a label; a screen reader on a field
with only a placeholder announces "edit text" once it has a value. A field
wrapped in its ``<label>`` is labelled too, and the scan accepts it. The TLE
fields are included in both the red and the blue form, so their ids carry
the side or the page would hold each id twice.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest

_FIELD = re.compile(r"<(input|select|textarea)\b([^>]*)>", re.S)
_ID = re.compile(r'\bid="([^"]+)"')
_TYPE = re.compile(r'\btype="([^"]+)"')
_LABEL_FOR = re.compile(r'<label\b[^>]*\bfor="([^"]+)"')
#: Types that are not typed into, or are named by the text around them.
_UNLABELLED_TYPES = frozenset({"hidden", "submit", "button", "reset", "image", "radio", "checkbox"})


def _inside_label(html: str, at: int) -> bool:
    """Whether position *at* is inside an open ``<label>`` element."""
    return html.rfind("<label", 0, at) > html.rfind("</label>", 0, at)


def _unlabelled(html: str) -> list[str]:
    """Each field in *html* that needs a label and is neither wrapped in one nor tied to one by id."""
    labelled = set(_LABEL_FOR.findall(html))
    missing = []
    for match in _FIELD.finditer(html):
        tag, attrs = match.groups()
        kind = _TYPE.search(attrs)
        if tag == "input" and kind and kind.group(1) in _UNLABELLED_TYPES:
            continue
        field_id = _ID.search(attrs)
        if _inside_label(html, match.start()) or (field_id and field_id.group(1) in labelled):
            continue
        missing.append(f"<{tag} {' '.join(attrs.split())[:80]}>")
    return missing


def _duplicate_ids(html: str) -> list[str]:
    return [i for i, n in Counter(_ID.findall(html)).items() if n > 1]


@pytest.fixture
def udl_state(auth_cookie: str) -> Iterator[Any]:
    from tests.integration.conftest import session_state

    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_available_sources)
    yield state
    state.udl_username, state.udl_available_sources = saved


def _page(client: Any, cookie: str) -> str:
    resp = client.get("/", cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


class TestTheOperatorPage:
    def test_every_field_is_labelled_before_udl_connects(
        self, client: Any, auth_cookie: str, udl_state: Any,
    ) -> None:
        udl_state.udl_username = None
        html = _page(client, auth_cookie)
        assert _unlabelled(html) == []
        assert 'id="udl-user"' in html and 'id="red-tle-name"' in html and 'id="blue-tle-name"' in html

    def test_every_field_is_labelled_once_connected(
        self, client: Any, auth_cookie: str, udl_state: Any,
    ) -> None:
        udl_state.udl_username = "operator"
        udl_state.udl_available_sources = ["18SDS"]
        html = _page(client, auth_cookie)
        assert _unlabelled(html) == []
        assert 'id="tle-source-select"' in html

    @pytest.mark.parametrize("connected", [False, True])
    def test_no_id_appears_twice(self, client: Any, auth_cookie: str, udl_state: Any, connected: bool) -> None:
        """The connected status partial used to repeat the TLE source panel on a full load."""
        udl_state.udl_username = "operator" if connected else None
        udl_state.udl_available_sources = ["18SDS"]
        assert _duplicate_ids(_page(client, auth_cookie)) == []


class TestTheFetchedTleFieldsKeepTheirSide:
    @pytest.mark.parametrize(("target", "side"), [("red-tle-fields", "red"), ("blue-tle-fields", "blue")])
    def test_the_side_comes_from_the_swap_target(
        self, client: Any, auth_cookie: str, udl_state: Any, target: str, side: str,
    ) -> None:
        udl_state.udl_username = None
        resp = client.get(
            "/udl/tle?satno=25544", cookies={"spectre_session": auth_cookie}, headers={"HX-Target": target},
        )
        assert resp.status_code == 200
        assert f'id="{side}-tle-name"' in resp.text and f'<label for="{side}-tle-text"' in resp.text
        assert _unlabelled(resp.text) == []

    def test_an_unknown_target_still_gets_labelled_fields(
        self, client: Any, auth_cookie: str, udl_state: Any,
    ) -> None:
        udl_state.udl_username = None
        resp = client.get("/udl/tle?satno=25544", cookies={"spectre_session": auth_cookie})
        assert 'id="tle-tle-name"' in resp.text
        assert _unlabelled(resp.text) == []


class TestTheUdlLoginForms:
    def test_the_retry_form_is_labelled(self, client: Any, auth_cookie: str) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from tests.conftest import csrf_headers

        refused = MagicMock(status_code=401, is_success=False)
        http = AsyncMock()
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        http.get = AsyncMock(return_value=refused)
        with patch("httpx.AsyncClient", return_value=http):
            resp = client.post(
                "/udl/login", data={"username": "u", "password": "p"},
                cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
            )
        assert 'id="udl-pass-retry"' in resp.text
        assert _unlabelled(resp.text) == []


def test_the_training_banner_is_a_note_not_a_live_status() -> None:
    """Web:S6819 asks for <output> over role=status; the banner is static, so it is a note."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / "training.html").read_text()
    banner = source[source.index('id="training-mode-banner"'):][:200]
    assert 'role="note"' in banner and 'role="status"' not in banner


class TestTheSweepTargetConfig:
    def test_the_response_time_per_target_is_labelled_and_shows_what_is_held(
        self, client: Any, auth_cookie: str, udl_state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SPC-022: the per-target response time is a labelled field on the sweep form, with the times held."""
        monkeypatch.setattr(udl_state, "response_time_by_target", {"BLUE-1": 6.0, "BLUE-2": 1.5})
        resp = client.get("/plan/threat/target-config?red_sat=RED-X", cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 200
        assert 'name="target_response_name"' in resp.text and 'name="target_response_h"' in resp.text
        assert _unlabelled(resp.text) == []
        text = " ".join(re.sub(r"<[^>]+>", " ", resp.text).split())
        assert "BLUE-1: 6 h" in text and "BLUE-2: 1.5 h" in text
        # A held time can be changed but not removed, so the operator is told how long it lasts.
        assert "A time held for a target can be changed, and is kept until you sign out." in text


class TestTheDecisionResults:
    """SPC-124 (49): the results carry a select, the histogram's cell, and a form per propagated cell."""

    def test_every_field_in_the_results_is_labelled(self) -> None:
        from spectre.domain.decision import evaluate_scenario
        from tests.unit.test_decision_sampled import _bound
        from tests.unit.test_decision_tca_histogram import _WithSpeeds
        from tests.unit.test_decision_trajectory import _render_with_links

        page = _render_with_links(evaluate_scenario(_bound(), sampler=_WithSpeeds()))
        assert 'id="tca-hist-cell"' in page and '<label for="tca-hist-cell"' in page
        assert "Show trajectory" in page
        assert _unlabelled(page) == []
        assert _duplicate_ids(page) == []


class TestTheGuardSeesAnUnlabelledField:
    """SPC-074: the scan, run on markup planted with each defect it exists to catch."""

    def test_a_placeholder_or_a_title_is_not_a_label(self) -> None:
        planted = '<input type="text" id="satno" placeholder="SATNO"><select name="mode"></select><textarea title="TLE"></textarea>'
        assert [field.split()[0] for field in _unlabelled(planted)] == ["<input", "<select", "<textarea"]

    def test_a_label_for_another_field_labels_nothing_here(self) -> None:
        assert _unlabelled('<label for="other">X</label><input id="satno">') == ['<input id="satno">']

    def test_a_closed_label_does_not_wrap_the_field_after_it(self) -> None:
        assert _unlabelled('<label>SATNO</label><input name="satno">') == ['<input name="satno">']

    def test_each_accepted_form_still_passes(self) -> None:
        assert _unlabelled('<label for="satno">SATNO</label><input type="text" id="satno">') == []
        assert _unlabelled('<label>SATNO <input type="text" name="satno"></label>') == []
        assert _unlabelled('<input type="hidden" name="csrf_token"><input type="submit">') == []

    def test_a_repeated_id_is_seen(self) -> None:
        assert _duplicate_ids('<input id="a"><select id="a"></select><p id="b">') == ["a"]
