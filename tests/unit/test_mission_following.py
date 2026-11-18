"""The mission after another in the campaign, read without indexing past the end (pythonbugs:S6466, release 0.48.6).

The routes used to index the campaign order at the position after the mission's own, guarded by a length test. The
helper walks the order instead, so the last mission and a mission the campaign does not hold have no next one, and
nothing can raise IndexError.
"""

from __future__ import annotations

import dataclasses
from itertools import pairwise

from spectre.training.missions import load_campaign
from spectre.web.routes.missions import _following


class TestFollowing:
    def test_each_mission_is_followed_by_the_next_in_campaign_order(self) -> None:
        campaign = load_campaign()
        order = campaign.missions
        assert len(order) >= 2
        for this, after in pairwise(order):
            assert _following(campaign, this) is after

    def test_the_last_mission_has_none_after_it(self) -> None:
        campaign = load_campaign()
        assert _following(campaign, campaign.missions[-1]) is None

    def test_a_mission_the_campaign_does_not_hold_has_none_after_it(self) -> None:
        campaign = load_campaign()
        stranger = dataclasses.replace(campaign.missions[0], id="not-in-this-campaign")
        assert _following(campaign, stranger) is None

    def test_an_empty_campaign_has_none_after_anything(self) -> None:
        campaign = load_campaign()
        empty = dataclasses.replace(campaign, missions=())
        assert _following(empty, campaign.missions[0]) is None
