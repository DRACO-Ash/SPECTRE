"""Pasted NOTSO messages that do not parse are counted on the page.

Audit F-089. A message without a NORAD ID dropped with no log, one that
raised went only to the server log, and the paste route warned only when
nothing at all parsed, so an operator pasting two messages saw one result and
no sign of the other.
"""

from __future__ import annotations

from tests.conftest import csrf_headers

_GOOD = (
    "MSGID: N1\nSATNO: 62902\nEFFECTIVE START: 2025-03-14T12:00:00Z\n"
    "EFFECTIVE END: 2025-03-14T18:00:00Z\nTYPE: MANOEUVRE"
)
_NO_SATNO = "MSGID: N2\nEFFECTIVE START: 2025-03-15T12:00:00Z\nTYPE: MANOEUVRE"


def test_a_message_without_a_satno_is_reported_as_dropped(client: object, auth_cookie: str) -> None:
    from spectre.astro.pattern_of_life import analyse_pattern_of_life
    from spectre.web.planning_state import get_session_state
    from tests.unit.test_dv_estimation import TestTwoTierReporting

    pol = analyse_pattern_of_life(TestTwoTierReporting._catalogue(), satno=62902, name="SIM")
    get_session_state("testadmin").last_pol_analysis = pol  # type: ignore[attr-defined]

    resp = client.post(  # type: ignore[attr-defined]
        "/pol/notso-correlate",
        data={"notso_text": _GOOD + "\n\n" + _NO_SATNO},
        cookies={"spectre_session": auth_cookie},
        headers=csrf_headers(auth_cookie),
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "1 of 2 messages parsed" in body
    assert "no labelled NORAD ID" in body
