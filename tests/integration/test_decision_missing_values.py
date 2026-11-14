"""A missing row value or weight is refused, naming the row and the field, never given a default (SPC-222, F-33).

Probe P-14 posted a truncated form: a row whose P, Conf or Gap was missing evaluated as P 0.5, Conf 0.5 or Gap 0.7,
and a missing weight took its default, so the scenario evaluated as if the operator had chosen those values. Each
missing value is now refused inline with a sentence naming the row and the field, and so is an action type that
names no listed type, which fell back to a manoeuvre.

The panel posts every one of these fields on every row, blanks included, and the server refuses a blank number as it
always has, so the panel's own submissions are unchanged; the test below reads the panel to show it. Nothing else
in SPECTRE posts to the route: no preset, no training scenario and no API caller builds a decision form. The fields
that are optional by design stay optional, and say so where they are declared: the hypothesis section, our burn
fields and the not-permitted fields, each absent as a whole meaning none; the hidden sweep fields; the scenario's
name; the selector, absent meaning the deployment's primary rule (SPC-194); and the tree's turn depth and stated
observation, absent meaning one turn and nothing stated.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.integration.test_decision_input_validation import _evaluate, _form

_ADVERSARY = {
    "adv_name": "name", "adv_type": "action type", "adv_prob": "probability (P)", "adv_conf": "confidence (Conf)",
    "adv_gap": "custody gap share (Gap)",
}
_FRIENDLY = {
    "fr_name": "name", "fr_type": "action type", "fr_cost": "cost", "fr_rev": "reversibility",
    "fr_time": "time to execute (hours)",
}
_WEIGHTS = {
    "w_custody": "custody", "w_ca": "closest-approach", "w_dv": "delta-V", "w_time": "time-to-execute",
    "w_rev": "reversibility",
}


def _complete(**overrides: Any) -> dict[str, Any]:
    """The shared form as built, with no column filled to its rows, so a short column reaches the route short."""
    return _form(pad=False, **overrides)


def _without(field: str, **overrides: Any) -> dict[str, Any]:
    form = _complete(**overrides)
    del form[field]
    return form


def _refusal(resp: Any) -> str:
    assert resp.status_code == 200
    found = re.fullmatch(r'<p class="error-msg">(.*)</p>', resp.text, re.S)
    assert found is not None, resp.text[:300]
    return found.group(1).replace("&#x27;", "'")


def _row_missing(side: str, row: int, field: str) -> str:
    return (
        f"{side} row {row} posts no {field}. Every row must post each of its fields, and a missing one is not given "
        "a default. Reload the panel and enter the row again."
    )


def test_the_complete_form_evaluates(client: Any, auth_cookie: str) -> None:
    resp = _evaluate(client, auth_cookie, _complete())
    assert resp.status_code == 200
    assert "error-msg" not in resp.text


@pytest.mark.parametrize(("field", "words"), list(_ADVERSARY.items()))
def test_an_adversary_field_not_posted_is_refused_naming_it(
    client: Any, auth_cookie: str, field: str, words: str,
) -> None:
    resp = _evaluate(client, auth_cookie, _without(field))
    assert _refusal(resp) == _row_missing("Adversary action", 1, words)


@pytest.mark.parametrize(("field", "words"), list(_ADVERSARY.items()))
def test_an_adversary_column_short_of_the_rows_names_the_row(
    client: Any, auth_cookie: str, field: str, words: str,
) -> None:
    two = {"adv_id": ["A1", "A2"], "adv_name": ["Approach", "Hold"], "adv_type": ["manoeuvre", "no_action"],
           "adv_prob": ["0.3", "0.3"], "adv_conf": ["0.7", "0.7"], "adv_gap": ["0.7", "0.7"]}
    two[field] = two[field][:1]
    resp = _evaluate(client, auth_cookie, _complete(**two))
    assert _refusal(resp) == _row_missing("Adversary action", 2, words)


@pytest.mark.parametrize(("field", "words"), list(_FRIENDLY.items()))
def test_a_friendly_field_not_posted_is_refused_naming_it(
    client: Any, auth_cookie: str, field: str, words: str,
) -> None:
    resp = _evaluate(client, auth_cookie, _without(field))
    assert _refusal(resp) == _row_missing("Friendly response", 1, words)


@pytest.mark.parametrize(("field", "words"), list(_FRIENDLY.items()))
def test_a_friendly_column_short_of_the_rows_names_the_row(
    client: Any, auth_cookie: str, field: str, words: str,
) -> None:
    two = {"fr_id": ["F1", "F2"], "fr_name": ["Hold", "Avoid"], "fr_type": ["no_action", "manoeuvre"],
           "fr_cost": ["0.0", "0.3"], "fr_rev": ["1.0", "0.8"], "fr_time": ["1", "6"]}
    two[field] = two[field][:1]
    resp = _evaluate(client, auth_cookie, _complete(**two))
    assert _refusal(resp) == _row_missing("Friendly response", 2, words)


def test_a_column_longer_than_the_rows_is_refused(client: Any, auth_cookie: str) -> None:
    resp = _evaluate(client, auth_cookie, _complete(adv_prob=["0.3", "0.3"]))
    assert _refusal(resp) == (
        "The adversary actions post 2 values of probability (P) for 1 row. Reload the panel and enter the rows again."
    )


@pytest.mark.parametrize(("field", "words"), list(_WEIGHTS.items()))
def test_a_weight_not_posted_is_refused_naming_it(client: Any, auth_cookie: str, field: str, words: str) -> None:
    expected = (
        f"The {words} weight is blank or was not posted. Every scoring weight must be given, and a missing one is "
        "not given its default. Enter it, or reload the panel."
    )
    assert _refusal(_evaluate(client, auth_cookie, _without(field))) == expected
    # A cleared field reaches the route as absent, so it is refused alike, never read as the default.
    assert _refusal(_evaluate(client, auth_cookie, _complete(**{field: ""}))) == expected


@pytest.mark.parametrize(("field", "side"), [("adv_type", "adversary action"), ("fr_type", "friendly response")])
def test_an_action_type_that_names_no_listed_type_is_refused(
    client: Any, auth_cookie: str, field: str, side: str,
) -> None:
    resp = _evaluate(client, auth_cookie, _complete(**{field: ["warp_drive"]}))
    assert _refusal(resp) == f"Choose a listed action type for {side} row 1."


def test_the_fields_optional_by_design_may_be_left_out(client: Any, auth_cookie: str) -> None:
    """No hypothesis section, no burn fields, no not-permitted fields, no selector, turn depth or observation."""
    form = _complete()
    for field in ("scenario_name", "strategy"):
        del form[field]
    resp = _evaluate(client, auth_cookie, form)
    assert resp.status_code == 200
    assert "error-msg" not in resp.text


def test_the_panel_posts_every_required_field_on_every_row(client: Any, auth_cookie: str) -> None:
    page = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie}).text
    form = page.split('<form hx-post="/plan/decision/evaluate"', 1)[1].split("</form>", 1)[0]
    templates = page.split('<template id="adv-row-template">', 1)[1]
    adversary_template = templates.split("</template>", 1)[0]
    friendly_template = templates.split('<template id="fr-row-template">', 1)[1].split("</template>", 1)[0]
    for name in (*_ADVERSARY, *_FRIENDLY, *_WEIGHTS):
        assert f'name="{name}"' in form, name
    for name in _ADVERSARY:
        assert f'name="{name}"' in adversary_template, name
    for name in _FRIENDLY:
        assert f'name="{name}"' in friendly_template, name
