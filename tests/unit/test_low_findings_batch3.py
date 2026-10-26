"""Low findings, audit batch 3 (F-269 to F-296). Each test names its finding."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WEB = _ROOT / "spectre" / "web"
_TEMPLATES = _WEB / "templates"


def _render(template: str, **context: object) -> str:
    from spectre.web.app import templates

    return templates.env.get_template(template).render(**context)


class TestF269MarkingAndVersionHaveOneSource:
    def test_splash_carries_the_package_version_and_the_marking(self) -> None:
        from spectre import __version__

        out = _render("partials/splash_overlay.html")
        assert f"v{__version__}" in out
        assert "v2.0.0" not in out or __version__ == "2.0.0"
        assert "3.4 s" in (_TEMPLATES / "partials" / "splash_overlay.html").read_text("utf-8")

    def test_no_template_hard_codes_the_marking(self) -> None:
        for name in ("base.html", "partials/splash_overlay.html"):
            text = (_TEMPLATES / name).read_text("utf-8")
            assert ">UNCLASSIFIED<" not in text, name

    @pytest.mark.parametrize(("marking", "expected"), [
        ("UNCLASSIFIED", "unclassified"),
        ("UNCLASSIFIED // PAIR", "unclassified"),
        ("OFFICIAL-SENSITIVE", "official"),
        ("SECRET", "secret"),
        ("SOMETHING NEW", "secret"),
    ])
    def test_banner_colour_falls_back_to_the_most_restrictive(self, marking: str, expected: str) -> None:
        from spectre.web.app import banner_class

        assert banner_class(marking) == expected

    def test_the_marking_is_read_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.config.settings import Settings

        monkeypatch.setenv("SPECTRE_CLASSIFICATION", "OFFICIAL")
        assert Settings().classification_marking == "OFFICIAL"
        monkeypatch.delenv("SPECTRE_CLASSIFICATION")
        assert Settings().classification_marking == "UNCLASSIFIED"


class TestF270CspCommentCountsAreTrue:
    def test_the_comment_matches_the_templates(self) -> None:
        templates = list(_TEMPLATES.rglob("*.html"))
        hx_on = sum(t.read_text("utf-8").count("hx-on:") for t in templates)
        styles = sum(t.read_text("utf-8").count("<style") for t in templates)
        words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "Seven", 8: "eight"}
        comment = (_WEB / "app.py").read_text("utf-8")
        assert f"{words[hx_on]} of them" in comment, hx_on
        assert f"{words[styles]}\n#     inline <style> blocks" in comment, styles


class TestF272ScenarioTlesPassTheirChecksums:
    def test_every_scenario_line(self) -> None:
        from spectre.astro.propagator import tle_checksum_valid

        text = (_ROOT / "spectre" / "training" / "config" / "scenarios.yaml").read_text("utf-8")
        lines = re.findall(r'tle_line[12]: "([^"]*)"', text)
        assert len(lines) >= 52
        bad = [ln for ln in lines if not tle_checksum_valid(ln)]
        assert not bad, f"{len(bad)} lines fail their checksum, first {bad[0]!r}"

    @pytest.mark.parametrize(("line", "ok"), [
        ("1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9999", True),
        ("1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9994", False),
        ("1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  999", False),
    ])
    def test_the_checksum_rule(self, line: str, ok: bool) -> None:
        from spectre.astro.propagator import tle_checksum_valid

        assert tle_checksum_valid(line) is ok

    def test_manual_entry_refuses_a_bad_checksum(self) -> None:
        from spectre.web.routes.operator import _add_refusal

        tle = ("1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9994\n"
               "2 25544  51.6420 195.0000 0001207  86.9689 273.1630 15.54320000365491")
        refusal = _add_refusal("A", tle)
        assert refusal is not None and "checksum" in refusal


class TestF273TutorialLabelsMatchTheButtons:
    def test_labels_and_no_efficiency_promise(self) -> None:
        text = (_ROOT / "spectre" / "training" / "config" / "tutorials.yaml").read_text("utf-8")
        yaml.safe_load(text)
        for stale in ('"View Scenario"', '"Start Scored Attempt"', '"Explore (Unscored)"', "efficiency score"):
            assert stale not in text, stale
        assert "View &amp; Load" in (_TEMPLATES / "partials" / "training_scenario_list.html").read_text("utf-8")
        assert "Start Scenario" in (_TEMPLATES / "partials" / "training_scenario_detail.html").read_text("utf-8")


class TestF275ObjectiveColoursAndEmptyCopy:
    def test_no_undefined_colour_helper(self) -> None:
        text = (_TEMPLATES / "partials" / "training_scenario_detail.html").read_text("utf-8")
        assert "cfg_axis_colour(" not in text and "axis_colour" in text

    def test_empty_list_does_not_blame_a_tutorial(self) -> None:
        out = _render("partials/training_scenario_list.html", free_play_scenarios=[], progress=None)
        assert "Orientation tutorial" not in out and "level" in out


class TestF276OneOpenTrainingSession:
    @pytest.fixture()
    async def db(self) -> object:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import spectre.training.models
        import spectre.web.models  # noqa: F401
        from spectre.web.database import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
        await engine.dispose()

    async def test_a_second_visit_reuses_the_open_session(self, db: object) -> None:
        from sqlalchemy import func, select

        from spectre.training.models import TrainingSession
        from spectre.web.routes.training import _open_session

        first = await _open_session("op", db)  # type: ignore[arg-type]
        second = await _open_session("op", db)  # type: ignore[arg-type]
        assert first.id == second.id
        count = (await db.execute(select(func.count()).select_from(TrainingSession))).scalar_one()  # type: ignore[attr-defined]
        assert count == 1

    async def test_a_racing_progress_insert_returns_the_existing_row(
        self, db: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.training.models import TrainingProgress
        from spectre.web.routes import training

        winner = TrainingProgress(username="op", current_level=1, unlocked_json="[]")
        db.add(winner)  # type: ignore[attr-defined]
        await db.commit()  # type: ignore[attr-defined]

        real_execute = db.execute  # type: ignore[attr-defined]
        calls = {"n": 0}

        async def first_select_misses(statement: object, *a: object, **k: object) -> object:
            calls["n"] += 1
            result = await real_execute(statement, *a, **k)
            if calls["n"] == 1:
                class _Empty:
                    def scalar_one_or_none(self) -> None:
                        return None
                return _Empty()
            return result

        monkeypatch.setattr(db, "execute", first_select_misses)
        progress = await training._get_or_create_progress("op", db)  # type: ignore[arg-type]
        assert progress.id == winner.id


class TestF271ClusteringConfigHasOneSetOfDefaults:
    def test_from_constants_with_nothing_equals_the_field_defaults(self) -> None:
        from tle_clustering.config import ClusteringConfig

        assert ClusteringConfig.from_constants({}) == ClusteringConfig()

    def test_a_changed_field_default_reaches_from_constants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import dataclasses

        from tle_clustering.config import ClusteringConfig

        field = next(f for f in dataclasses.fields(ClusteringConfig) if f.name == "raan_tolerance_deg")
        monkeypatch.setattr(field, "default", 0.25)
        assert ClusteringConfig.from_constants({}).raan_tolerance_deg == 0.25

    def test_docstring_names_modules_that_exist(self) -> None:
        from tle_clustering import config

        doc = config.ClusteringConfig.__doc__ or ""
        assert "parser.TLERecord" not in doc and "clustering._normalise" not in doc
        assert "models.TLERecord" in doc and "_axis_distances" in doc


class TestF274OneCopyOfTheColourMaths:
    @pytest.mark.parametrize("module", [
        "test_focus_visible_indicator.py", "test_contrast_floors.py", "test_dark_surfaces_in_steel.py",
    ])
    def test_no_private_copy(self, module: str) -> None:
        text = (_ROOT / "tests" / "unit" / module).read_text("utf-8")
        for name in ("_luminance", "_ratio", "_over"):
            assert f"def {name}(" not in text, (module, name)
        assert text.count("def _rule_block(") <= 1, module

    def test_the_shared_maths(self) -> None:
        from tests.unit._css import over, ratio

        assert round(ratio("#000000", "#FFFFFF"), 2) == 21.0
        assert over("#FFFFFF", 0.5, "#000000") == "#808080"


def _text(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


class TestF277SuidSweepRunsAsRootAndFailsLoud:
    @pytest.mark.parametrize("path", [
        ".github/workflows/ci.yml", "scripts/verify-container.sh", "scripts/simulate-pipeline.sh",
    ])
    def test_sweep(self, path: str) -> None:
        text = _text(path)
        assert any("docker run" in ln and "--user 0" in ln for ln in text.splitlines()), path
        assert "-type d \\) -print'" in text, path
        assert "-perm /6000 \\( -type f -o -type d \\) 2>/dev/null" not in text


class TestF278QualityGateScope:
    def test_quality_job_runs_on_pull_requests_only(self) -> None:
        ci = yaml.safe_load(_text(".github/workflows/ci.yml"))
        assert ci["jobs"]["quality"]["if"] == "github.event_name == 'pull_request'"

    def test_whole_repo_coverage_precedes_the_early_exit(self) -> None:
        text = _text("scripts/check-quality.sh")
        assert text.index("Whole-repository coverage against the house standard ==") < text.index(
            "Nothing to check."
        )
        assert "--include-untracked" in text


class TestF279HooksUseTheLockedTools:
    def test_no_pinned_tool_repos(self) -> None:
        cfg = yaml.safe_load(_text(".pre-commit-config.yaml"))
        repos = {r["repo"] for r in cfg["repos"]}
        assert not repos & {
            "https://github.com/astral-sh/ruff-pre-commit",
            "https://github.com/PyCQA/bandit",
            "https://github.com/pre-commit/mirrors-mypy",
        }
        local = next(r for r in cfg["repos"] if r["repo"] == "local")
        assert {h["id"] for h in local["hooks"]} == {"ruff", "bandit", "mypy"}


class TestF287CiIsBounded:
    def test_every_job_has_a_timeout_and_the_boot_check_is_bounded(self) -> None:
        ci = yaml.safe_load(_text(".github/workflows/ci.yml"))
        assert all("timeout-minutes" in job for job in ci["jobs"].values())
        assert "timeout 60 docker run --rm spectre:ci" in _text(".github/workflows/ci.yml")


class TestF288NoFixedTmpPaths:
    @pytest.mark.parametrize("path", ["scripts/check-quality.sh", "scripts/simulate-pipeline.sh"])
    def test_no_fixed_out_files(self, path: str) -> None:
        assert not re.search(r"/tmp/[a-z-]+\.out", _text(path))


class TestF289And290Packaging:
    def test_a_missing_ledger_fails(self) -> None:
        text = _text("scripts/package-appstore.sh")
        assert 'if [ ! -f "$LEDGER" ]; then' in text

    def test_manifest_search_is_recursive_and_complete(self) -> None:
        text = _text("scripts/package-appstore.sh")
        assert 'find "$STAGE" -type f' in text
        for name in ("requirements.in", "uv.lock", "Pipfile.lock", "pdm.lock"):
            assert f"-name {name}" in text, name
        assert "requirements-runtime" not in re.search(r'found=\$\(find.*?-print\)', text, re.S).group(0)


class TestF291And292IgnoreRulesAreScoped:
    @pytest.mark.parametrize("rule", ["env/", "lib/", "lib64/", "logs/", "parts/", "var/"])
    def test_gitignore_root_rules_are_anchored(self, rule: str) -> None:
        lines = _text(".gitignore").splitlines()
        assert rule not in lines and f"/{rule}" in lines

    def test_nested_paths_are_not_ignored(self) -> None:
        import shutil
        import subprocess

        git = shutil.which("git")
        if git is None:
            pytest.skip("no git executable in this environment")
        result = subprocess.run(
            [git, "check-ignore", "spectre/lib/x.py", "tle_clustering/env/x.py"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        )
        assert result.stdout == ""

    @pytest.mark.parametrize("rule", ["**/.env", "**/.env.*", "**/__pycache__/", "**/*.py[cod]"])
    def test_dockerignore_reaches_nested_copies(self, rule: str) -> None:
        assert rule in _text(".dockerignore").splitlines()


class TestF296TheScannerVersionMustResolve:
    def test_the_audit_requires_the_scanner_python(self) -> None:
        text = _text("scripts/audit-dependencies.sh")
        assert 'SCANNER_RESOLVES" -ne 1' in text
