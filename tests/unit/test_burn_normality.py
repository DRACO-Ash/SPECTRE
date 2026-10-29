"""Is this burn normal for this object? (SPC-009, the operator's first question.)

Each class pins one rule of :func:`spectre.domain.normality.judge_burn`. The
histories are built by hand so every figure in the sentence can be checked
against the input, not against the code under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectre.domain.normality import Burn, Normality, judge_burn, judge_history

_START = datetime(2026, 1, 1, tzinfo=UTC)
_SK = "station keeping"


def _sk_history(count: int = 20, every_days: float = 14.0, dv: float = 1.8) -> list[Burn]:
    """A GEO object keeping station: one small burn a fortnight."""
    return [
        Burn(epoch=_START + timedelta(days=every_days * (i + 1)), delta_v_m_s=dv + 0.05 * (i % 5), label=_SK)
        for i in range(count)
    ]


def _after(history: list[Burn], days: float, dv: float, label: str = _SK) -> Burn:
    return Burn(epoch=history[-1].epoch + timedelta(days=days), delta_v_m_s=dv, label=label)


class TestRoutine:
    def test_a_burn_like_its_predecessors_is_routine(self) -> None:
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 1.9), history, _START)
        assert judged.verdict is Normality.ROUTINE
        assert judged.sentence.startswith("Routine for this object")
        assert judged.sentence == (
            "Routine for this object: this 1.9 m/s station keeping is in line with "
            "its 20 earlier burns over 294 days (1.8 to 2.0 m/s)."
        )


class TestUnprecedented:
    def test_a_kind_of_burn_never_seen_before(self) -> None:
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 1.9, label="relocation"), history, _START)
        assert judged.verdict is Normality.UNPRECEDENTED
        assert judged.sentence.startswith("Unlike anything in its last")
        assert "No earlier burn was a relocation." in judged.sentence

    def test_far_larger_than_any_earlier_burn(self) -> None:
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 14.0), history, _START)
        assert judged.verdict is Normality.UNPRECEDENTED
        assert "The largest of its 20 earlier burns was 2.0 m/s." in judged.sentence

    def test_just_above_the_largest_is_not_unprecedented(self) -> None:
        # Element-set noise moves a station-keeping burn by tenths of a m/s; a
        # burn a hair above the largest is not "unlike anything".
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 2.1), history, _START)
        assert judged.verdict is not Normality.UNPRECEDENTED

    def test_half_as_large_again_is_unusual_not_unprecedented(self) -> None:
        # 21 m/s among 14 m/s raises read "unlike anything in 80 days" at a
        # factor of 1.5; it is large for its kind, which is unusual.
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 3.0), history, _START)
        assert judged.verdict is Normality.UNUSUAL


class TestUnusual:
    def test_much_sooner_than_its_usual_cadence(self) -> None:
        history = _sk_history()
        judged = judge_burn(_after(history, 2, 1.9), history, _START)
        assert judged.verdict is Normality.UNUSUAL
        assert "It came 2 days after the previous burn, against a usual 14." in judged.sentence

    def test_a_kind_it_rarely_flies(self) -> None:
        history = _sk_history(30)
        history.insert(10, Burn(epoch=history[9].epoch + timedelta(days=1), delta_v_m_s=3.0, label="plane change"))
        judged = judge_burn(_after(history, 14, 3.0, label="plane change"), history, _START)
        assert judged.verdict is Normality.UNUSUAL
        assert "1 of its 31 earlier burns was a plane change." in judged.sentence

    def test_large_for_its_kind(self) -> None:
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 2.9), history, _START)
        assert judged.verdict is Normality.UNUSUAL
        assert "Larger than any of its 20 earlier station keeping burns (up to 2.0 m/s)." in judged.sentence


class TestNotEnoughHistory:
    def test_too_few_earlier_burns(self) -> None:
        history = _sk_history(3)
        judged = judge_burn(_after(history, 14, 40.0, label="relocation"), history, _START)
        assert judged.verdict is Normality.NOT_ENOUGH_HISTORY
        assert judged.sentence == "Too little history to judge: 3 earlier burns over 56 days."

    def test_too_short_a_history(self) -> None:
        history = _sk_history(10, every_days=1.0)
        judged = judge_burn(_after(history, 1, 1.9), history, _START)
        assert judged.verdict is Normality.NOT_ENOUGH_HISTORY


class TestWhatTheVerdictRestsOn:
    def test_it_says_it_judged_against_this_object_only(self) -> None:
        history = _sk_history()
        judged = judge_burn(_after(history, 14, 1.9), history, _START)
        assert "this object's own history" in judged.basis
        assert "below the detection floor" in judged.basis

    def test_only_burns_before_it_count(self) -> None:
        # A later burn must never inform the verdict on an earlier one.
        history = _sk_history()
        later = _after(history, 30, 80.0, label="relocation")
        judged = judge_burn(history[-1], [*history[:-1], later], _START)
        assert judged.prior_burns == 19


class TestJudgingAWholeHistory:
    def test_every_burn_is_judged_against_those_before_it(self) -> None:
        history = [*_sk_history(), _after(_sk_history(), 14, 40.0, label="relocation")]
        judged = judge_history(history, _START)
        assert len(judged) == 21
        assert judged[0].verdict is Normality.NOT_ENOUGH_HISTORY
        assert judged[-1].verdict is Normality.UNPRECEDENTED

    def test_no_burns_judge_to_nothing(self) -> None:
        assert judge_history([], _START) == []
