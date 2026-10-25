"""The bundled HRR watchlist, and the delivery that kept failing.

The operator's own ``HRR_List.json`` is gitignored and dockerignored on
purpose: it is operational data and belongs on the data volume, not in a
source tree or an image. The consequence was that a deployed instance had no
watchlist at all, and the threat sweep and the asset screen both stalled at
"fetch the HRR list from the UDL panel first".

Two separate things had to be true for that to keep happening, and both are
pinned here:

  * a bundled bootstrap list has to EXIST and load, and
  * it has to be committable. ``.gitignore`` carried an unanchored ``data/``,
    which matches at any depth, so anything added under ``spectre/data/`` was
    silently ignored. The JSON already there survives only because it predates
    the rule.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED = _ROOT / "spectre" / "data" / "hrr_default.json"
_RED_COUNTRIES = {"CHN", "RUS", "IRN", "PRK"}

# Resolved once, absolutely: a bare executable name goes through PATH, which a
# test should not depend on and the analyser flags (S607).
_GIT = shutil.which("git")


@pytest.fixture(scope="module")
def notification() -> dict:
    parsed = json.loads(_BUNDLED.read_text(encoding="utf-8"))
    assert isinstance(parsed, list) and parsed, "must be a list of notifications"
    return parsed[0]


def _repository_only() -> str:
    """Return the git executable, or skip. Two things can be missing, not one.

    Inside the submission package there is no ``.git`` to ask about, which the
    previous version of this guard checked for.

    Inside the platform's Test image there IS a ``.git``, because the runner's
    helper container performs the checkout, but there is no ``git`` EXECUTABLE,
    because the job image is a bare Python one. A guard that tests only for the
    directory therefore passes on the platform and the test then dies on
    ``FileNotFoundError: [Errno 2] No such file or directory: 'git'``. That is
    what turned four of these red on the submission pipeline while they passed
    in every environment they had ever been run in.
    """
    if _GIT is None:
        pytest.skip("no git executable: the runner's job image ships none")
    if not (_ROOT / ".git").exists():
        pytest.skip("no git repository: running from the submission package")
    return _GIT


class TestItCanActuallyBeDelivered:
    """A file git refuses to track ships nowhere."""

    def test_the_bundled_list_is_not_gitignored(self) -> None:
        git = _repository_only()
        result = subprocess.run(  # noqa: S603
            [git, "check-ignore", "-v", str(_BUNDLED.relative_to(_ROOT))],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0, (
            "the bundled watchlist is gitignored, so it can never be "
            f"committed and never ships: {result.stdout.strip()}"
        )

    def test_nothing_under_the_package_data_dir_is_ignored(self) -> None:
        git = _repository_only()
        """The general rule, not just this one file.

        An unanchored data/ in .gitignore matches at any depth. The files
        already in spectre/data/ survive only because they predate it, so the
        rule looks harmless right up until someone adds the next one.
        """
        probe = _ROOT / "spectre" / "data" / "_ignore_probe.tmp"
        probe.write_text("", encoding="utf-8")
        try:
            result = subprocess.run(  # noqa: S603
                [git, "check-ignore", "-q", str(probe.relative_to(_ROOT))],
                cwd=_ROOT, capture_output=True, text=True, check=False,
            )
            assert result.returncode != 0, (
                "a new file under spectre/data/ is gitignored. Package data "
                "lives here and must be committable; anchor the data/ rule to "
                "the repository root instead."
            )
        finally:
            probe.unlink(missing_ok=True)

    def test_the_runtime_data_volume_is_still_ignored(self) -> None:
        git = _repository_only()
        """Anchoring must not start committing the operator's runtime data."""
        (_ROOT / "data").mkdir(exist_ok=True)
        probe = _ROOT / "data" / "_ignore_probe.tmp"
        probe.write_text("", encoding="utf-8")
        try:
            result = subprocess.run(  # noqa: S603
                [git, "check-ignore", "-q", "data/_ignore_probe.tmp"],
                cwd=_ROOT, capture_output=True, text=True, check=False,
            )
            assert result.returncode == 0, (
                "the runtime data volume is no longer ignored; operator data "
                "would be committed"
            )
        finally:
            probe.unlink(missing_ok=True)

    def test_the_operators_own_list_stays_ignored_everywhere(self) -> None:
        git = _repository_only()
        """HRR_List.json is their operational product, not ours to commit."""
        for rel in ("HRR_List.json", "spectre/data/HRR_List.json"):
            probe = _ROOT / rel
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("", encoding="utf-8")
            try:
                result = subprocess.run(  # noqa: S603
                    [git, "check-ignore", "-q", rel],
                    cwd=_ROOT, capture_output=True, text=True, check=False,
                )
                assert result.returncode == 0, f"{rel} would be committed"
            finally:
                probe.unlink(missing_ok=True)


class TestTheListIsUsable:
    def test_it_has_both_sides(self, notification: dict) -> None:
        body = notification["msgBody"]
        red = [e for e in body if e["country"] in _RED_COUNTRIES]
        blue = [e for e in body if e["country"] not in _RED_COUNTRIES]
        assert len(blue) >= 10, "assets to screen"
        assert len(red) >= 10, "candidate actors to screen against"

    def test_every_object_carries_a_usable_element_set(self, notification: dict) -> None:
        """An object list without orbits populates a dropdown that then fails."""
        from spectre.astro.constants import R_EARTH
        from spectre.astro.propagator import TLEOrbit
        from spectre.web.routes.udl import _parse_tle_epoch

        for entry in notification["msgBody"]:
            epoch = _parse_tle_epoch(entry["line1"])
            assert epoch is not None, f"{entry['satNo']}: no readable epoch"
            state = TLEOrbit(f"{entry['line1']}\n{entry['line2']}").propagate(epoch)
            assert state.r_mag > R_EARTH, f"{entry['satNo']}: propagates inside the Earth"

    def test_the_declared_regime_matches_the_element_set(self, notification: dict) -> None:
        """The screen filters candidates on the label, so it must be true."""
        from spectre.astro.propagator import regime_from_tle

        for entry in notification["msgBody"]:
            tle = f"{entry['line1']}\n{entry['line2']}"
            assert regime_from_tle(tle) == entry["orbitRegime"], (
                f"{entry['commonName']} is labelled {entry['orbitRegime']} but "
                f"its element set is {regime_from_tle(tle)}"
            )

    def test_the_red_objects_join_to_the_intelligence_records(
        self, notification: dict
    ) -> None:
        """Without the join the composite verdict has nothing to work with."""
        from spectre.data.intel import get_intel

        red = [e for e in notification["msgBody"] if e["country"] in _RED_COUNTRIES]
        matched = [e for e in red if get_intel(e["satNo"])]
        assert len(matched) == len(red), (
            "every red object in the bootstrap list must have an assessment: "
            f"{[e['commonName'] for e in red if not get_intel(e['satNo'])]}"
        )


class TestProvenanceIsDeclared:
    """These orbits are generated, not observed. Nothing may imply otherwise."""

    def test_every_element_set_is_marked_not_live(self, notification: dict) -> None:
        for entry in notification["msgBody"]:
            assert entry["tleDataMode"] == "SYNTHETIC", (
                f"{entry['commonName']} would be presented as tracking data"
            )

    def test_the_file_says_what_it_is(self, notification: dict) -> None:
        comment = notification.get("_comment", "")
        assert "NOT AN OPERATIONAL PRODUCT" in comment
        assert "SYNTHETIC" in comment
        assert notification["source"] != "JCO", (
            "it must not claim the source of the real watchlist"
        )

    def test_a_udl_fetch_replaces_a_synthetic_element_set(self) -> None:
        """Otherwise connecting to UDL changes nothing and nobody notices."""
        from spectre.web.planning_state import SessionState
        from spectre.web.routes.threat import _needs_live_tle

        state = SessionState()
        state.hrr_tle_cache["41838"] = "1 ...\n2 ..."
        state.hrr_tle_data_mode["41838"] = "SYNTHETIC"
        assert _needs_live_tle(state, "41838"), (
            "a synthetic element set must be refreshed, not treated as cached"
        )

        state.hrr_tle_data_mode["41838"] = "REAL"
        assert not _needs_live_tle(state, "41838"), (
            "a real element set must not be refetched on every sweep"
        )
        assert _needs_live_tle(state, "99999"), "an absent object needs fetching"


class TestTheLoaderFindsIt:
    def test_the_bundled_path_is_a_candidate_and_ranks_last(self) -> None:
        from spectre.web import app as app_module

        paths = app_module._hrr_candidate_paths()
        assert paths[-1] == app_module._HRR_BUNDLED, (
            "the bundled list is the floor; an operator-supplied file wins"
        )
        assert app_module._HRR_BUNDLED.exists()

    def test_loading_it_populates_objects_and_element_sets(self) -> None:
        from spectre.web import app as app_module
        from spectre.web.planning_state import (
            get_default_hrr_objects,
            get_default_hrr_tles,
        )

        app_module._load_hrr_from_disk()
        objects = get_default_hrr_objects()
        tles, modes = get_default_hrr_tles()
        assert len(objects) >= 20
        assert len(tles) == len(objects), (
            "every object needs an orbit, or the screen populates a dropdown "
            "that refuses to run"
        )
        assert set(modes.values()) == {"SYNTHETIC"}

    def test_a_new_session_inherits_both(self) -> None:
        from spectre.web import app as app_module
        from spectre.web.planning_state import clear_session_state, get_session_state

        app_module._load_hrr_from_disk()
        clear_session_state("bootstrap-probe")
        state = get_session_state("bootstrap-probe")
        try:
            assert state.hrr_objects, "the watchlist did not reach the session"
            assert state.hrr_tle_cache, "the element sets did not reach the session"
            assert len(state.hrr_tle_cache) == len(state.hrr_objects)
        finally:
            clear_session_state("bootstrap-probe")
