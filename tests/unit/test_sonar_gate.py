"""The SonarQube gate's parts that run without docker (owner's instruction, 18 November 2026).

The gate is zero open issues and zero unreviewed hotspots across the whole
package, measured by SonarQube at check time. Its live run needs docker and is
tests/integration/test_sonar_gate_live.py; these cases hold everything around
it: the rule set it builds, the report it reads, the packager and CI that call
it, and the refusal when docker is missing.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest
import yaml

from tests.unit.test_deployment_contract import _repo_only

_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _ROOT / "scripts" / "sonar_gate.py"
_GATE = _ROOT / "scripts" / "sonar-gate.sh"
_PROFILE = _ROOT / "scripts" / "sonar-profile.json"
_SH = shutil.which("sh") or "/bin/sh"

# scripts/ is stripped from the App Store package, where this suite also runs.
if not _HELPER.is_file():
    pytest.skip("scripts/ is excluded from the submission package", allow_module_level=True)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sonar_gate", _HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sonar_gate"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()

#: Every rule the platform's SonarQube has raised on SPECTRE: its own list
#: (platform-rules.txt) and every rule in the full 0.48.5 issue export.
_PLATFORM_RAISED = frozenset({
    # platform-rules.txt
    "python:S5655", "python:S1192", "python:S5886", "python:S3358", "python:S8495", "python:S1172",
    "python:S7508", "python:S8410", "python:S1940", "python:S8786", "python:S1244", "python:S3776",
    "javascript:S3776", "javascript:S6557", "javascript:S3358", "javascript:S7721", "javascript:S6661",
    "javascript:S6582", "javascript:S7765", "javascript:S4138", "javascript:S7781", "javascript:S1481",
    "Web:S6853", "Web:S6825", "Web:S6819", "Web:S7927", "Web:InputWithoutLabelCheck",
    # issues-0485.json, beyond the list above
    "python:S4830", "python:S5863", "python:S7503", "python:S8392", "python:S8572",
    "javascript:S9383", "css:S4656", "Web:ImgWithoutAltCheck", "Web:S5256", "Web:S9379",
    "Web:TableHeaderHasIdOrScopeCheck",
})


def _profile() -> dict[str, Any]:
    return json.loads(_PROFILE.read_text(encoding="utf-8"))


class TestTheProfile:
    def test_it_is_well_formed(self) -> None:
        assert gate.profile_problems(_profile()) == []
        assert gate.load_profile(_PROFILE)["name"] == "SPECTRE gate"

    def test_it_names_every_rule_the_platform_has_raised(self) -> None:
        missing = _PLATFORM_RAISED - gate.profile_rules(_profile())
        assert not missing, f"the gate would not run these platform rules: {sorted(missing)}"

    def test_the_one_rule_it_cannot_run_is_declared_with_a_reason(self) -> None:
        """pythonbugs:S6466 ships only in the commercial editions; it must not vanish silently."""
        unavailable = _profile()["not_in_community_build"]
        assert "pythonbugs:S6466" in unavailable
        assert "missions.py" in unavailable["pythonbugs:S6466"]

    def test_each_language_builds_on_sonar_way_extended(self) -> None:
        """26.11 ships Sonar way core, extended and comprehensive; there is no plain Sonar way."""
        assert {spec["base"] for spec in _profile()["languages"].values()} == {"Sonar way extended"}

    @pytest.mark.parametrize(("mutate", "complaint"), [
        (lambda p: p["languages"]["py"]["rules"].append("javascript:S3776"), "not a py rule key"),
        (lambda p: p["languages"]["js"]["rules"].append("javascript:S3776"), "listed twice"),
        (lambda p: p["languages"]["css"].pop("base"), "no base profile"),
        (lambda p: p["languages"].pop("web"), "languages must be exactly"),
        (lambda p: p["languages"]["web"].update(rules=[]), "no rules"),
        (lambda p: p["not_in_community_build"].update({"pythonbugs:S1": ""}), "reason"),
    ])
    def test_a_malformed_profile_is_refused(self, mutate: Any, complaint: str, tmp_path: Path) -> None:
        profile = _profile()
        mutate(profile)
        assert any(complaint in problem for problem in gate.profile_problems(profile))
        broken = tmp_path / "profile.json"
        broken.write_text(json.dumps(profile), encoding="utf-8")
        with pytest.raises(gate.GateError, match="malformed"):
            gate.load_profile(broken)


_ISSUES_PAGE = {
    "paging": {"pageIndex": 1, "pageSize": 500, "total": 2},
    "issues": [
        {"component": "spectre-gate:spectre/astro/transfers.py", "line": 27, "rule": "python:S1244",
         "type": "BUG", "severity": "MAJOR", "message": "Do not perform equality checks\n with floating point values."},
        {"component": "spectre-gate:spectre/web/static/style.css", "rule": "css:S4656",
         "type": "CODE_SMELL", "severity": "MAJOR", "message": "Unexpected duplicate \"color\"."},
    ],
}
_HOTSPOTS_PAGE = {
    "paging": {"pageIndex": 1, "pageSize": 500, "total": 1},
    "hotspots": [
        {"component": "spectre-gate:spectre/config/settings.py", "line": 259, "ruleKey": "python:S4830",
         "vulnerabilityProbability": "HIGH", "message": "Enable server certificate validation."},
    ],
}


class TestReadingTheReport:
    def test_an_issue_prints_as_file_line_rule_message(self) -> None:
        issue, css = gate.findings_from_issues([_ISSUES_PAGE], "spectre-gate")
        assert issue.as_line() == (
            "spectre/astro/transfers.py:27 python:S1244 Do not perform equality checks with floating point values."
        )
        assert css.line == 0, "a file-level issue has no line"

    def test_a_hotspot_is_read_from_its_own_fields(self) -> None:
        (hotspot,) = gate.findings_from_hotspots([_HOTSPOTS_PAGE], "spectre-gate")
        assert (hotspot.file, hotspot.line, hotspot.rule, hotspot.type) == (
            "spectre/config/settings.py", 259, "python:S4830", "SECURITY_HOTSPOT",
        )

    @pytest.mark.parametrize(("component", "path"), [
        ("spectre-gate:spectre/web/app.py", "spectre/web/app.py"),
        ("spectre-gate", "spectre-gate"),
        ("other:x.py", "other:x.py"),
    ])
    def test_the_project_key_is_stripped_from_the_component(self, component: str, path: str) -> None:
        assert gate.component_path(component, "spectre-gate") == path

    def test_one_issue_fails_and_none_passes(self) -> None:
        issues = gate.findings_from_issues([_ISSUES_PAGE], "k")
        hotspots = gate.findings_from_hotspots([_HOTSPOTS_PAGE], "k")
        failed = gate.build_report("k", issues, hotspots)
        assert failed["verdict"] == "FAIL"
        assert failed["counts"] == {
            "issues": 2, "hotspots_to_review": 1,
            "by_rule": {"css:S4656": 1, "python:S1244": 1, "python:S4830": 1},
        }
        assert set(failed["issues"][0]) == {"file", "line", "rule", "type", "severity", "message"}
        assert gate.build_report("k", [], [])["verdict"] == "PASS"
        assert gate.build_report("k", [], hotspots)["verdict"] == "FAIL", "an unreviewed hotspot fails the gate"

    def test_the_task_id_is_read_from_report_task(self, tmp_path: Path) -> None:
        task = tmp_path / "report-task.txt"
        task.write_text("projectKey=k\nceTaskId=AZ-123\nceTaskUrl=http://x/api/ce/task?id=AZ-123\n", encoding="utf-8")
        assert gate.read_report_task(task) == "AZ-123"
        task.write_text("projectKey=k\n", encoding="utf-8")
        with pytest.raises(gate.GateError, match="no ceTaskId"):
            gate.read_report_task(task)
        with pytest.raises(gate.GateError, match="no report-task"):
            gate.read_report_task(tmp_path / "absent.txt")

    def test_nosonar_markers_are_listed_not_hidden(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\ny = 2  # NOSONAR\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "b.py").write_text("# NOSONAR\n", encoding="utf-8")
        (tmp_path / "c.txt").write_text("NOSONAR\n", encoding="utf-8")
        assert gate.nosonar_lines(tmp_path) == ["a.py:2"]


class TestSecrets:
    def test_a_generated_password_meets_the_server_rule_and_is_random(self) -> None:
        first, second = gate.generate_password(), gate.generate_password()
        assert first != second
        for password in (first, second):
            assert len(password) >= 12
            assert re.search(r"[A-Z]", password) and re.search(r"[a-z]", password)
            assert re.search(r"\d", password) and re.search(r"[^A-Za-z0-9]", password)

    @pytest.mark.parametrize(("text", "auth", "token"), [
        ("admin:pw\n", "admin:pw", None),
        ("squ_abc\n", "squ_abc:", "squ_abc"),
        ('{"auth": "admin:pw", "token": "squ_t"}', "admin:pw", "squ_t"),
    ])
    def test_credentials_files_in_each_accepted_form(self, text: str, auth: str, token: str | None) -> None:
        parsed = gate.parse_credentials(text)
        assert parsed["auth"] == auth
        assert parsed.get("token") == token

    @pytest.mark.parametrize("text", ["", "   \n", "{not json", '{"token": "x"}'])
    def test_unusable_credentials_are_refused(self, text: str) -> None:
        with pytest.raises(gate.GateError):
            gate.parse_credentials(text)

    def test_the_secrets_file_is_private(self, tmp_path: Path) -> None:
        target = tmp_path / "credentials.json"
        gate._write_secrets(target, {"auth": "admin:pw", "token": "t"})
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_no_secret_is_committed_in_the_gate(self) -> None:
        text = _GATE.read_text(encoding="utf-8") + _HELPER.read_text(encoding="utf-8")
        assert not re.search(r"squ_[0-9a-f]{20,}|sqa_[0-9a-f]{20,}", text)
        assert "set -x" not in _GATE.read_text(encoding="utf-8")


class _FakeSonar(http.server.BaseHTTPRequestHandler):
    """Answers the three reads the report makes, with paging over two pages."""

    issues: ClassVar[list[dict[str, Any]]] = []

    def _answer_get(self) -> None:
        path, _, query = self.path.partition("?")
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        if path == "/api/server/version":
            self._send(b"26.11.0.134175", "text/plain")
            return
        page = int(params.get("p", "1"))
        if path == "/api/issues/search":
            chunk = self.issues[(page - 1) * 500:page * 500]
            body = {"paging": {"pageIndex": page, "pageSize": 500, "total": len(self.issues)}, "issues": chunk}
        elif path == "/api/hotspots/search":
            body = {"paging": {"pageIndex": page, "pageSize": 500, "total": 0}, "hotspots": []}
        else:
            self.send_error(404)
            return
        self._send(json.dumps(body).encode(), "application/json")

    # The stdlib dispatches GET to a method named do_GET; bound by assignment
    # so the method itself keeps a snake_case name.
    do_GET = _answer_get

    def _send(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


@pytest.fixture
def fake_sonar() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeSonar)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class TestTheReportCommand:
    """The report subcommand, end to end against a fake server: pages, prints, verdict."""

    def _run(self, host: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, dict[str, Any]]:
        secrets_file = tmp_path / "credentials.json"
        gate._write_secrets(secrets_file, {"auth": "admin:pw", "token": "t"})
        out = tmp_path / "report.json"
        code = gate.main(["report", "--host", host, "--secrets", str(secrets_file), "--project", "spectre-gate",
                          "--out", str(out), "--profile", str(_PROFILE)])
        return code, capsys.readouterr().out, json.loads(out.read_text(encoding="utf-8"))

    def test_every_page_is_read_and_one_issue_fails(
        self, fake_sonar: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _FakeSonar.issues = [
            {"component": f"spectre-gate:spectre/m{i}.py", "line": i, "rule": "python:S1192",
             "type": "CODE_SMELL", "severity": "CRITICAL", "message": "Define a constant."}
            for i in range(1, 603)
        ]
        code, printed, report = self._run(fake_sonar, tmp_path, capsys)
        assert code == 1
        assert report["counts"]["issues"] == 602, "the second page was not read"
        assert "spectre/m1.py:1 python:S1192 Define a constant." in printed
        assert report["server_version"] == "26.11.0.134175"
        assert len(report["profile_sha256"]) == 64

    def test_a_clean_analysis_passes(self, fake_sonar: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _FakeSonar.issues = []
        code, printed, report = self._run(fake_sonar, tmp_path, capsys)
        assert (code, report["verdict"]) == (0, "PASS")
        assert "0 open issues, 0 security hotspots to review" in printed

    def test_an_unreachable_server_is_no_verdict_not_a_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        secrets_file = tmp_path / "credentials.json"
        gate._write_secrets(secrets_file, {"auth": "admin:pw", "token": "t"})
        code = gate.main(["report", "--host", "http://127.0.0.1:9", "--secrets", str(secrets_file),
                          "--project", "k", "--out", str(tmp_path / "r.json")])
        assert code == 2
        assert "GATE ERROR" in capsys.readouterr().err


class TestTheShellGate:
    def test_both_images_are_pinned_by_digest(self) -> None:
        text = _GATE.read_text(encoding="utf-8")
        images = dict(re.findall(r'^(SONARQUBE_IMAGE|SCANNER_IMAGE)="([^"]+)"', text, re.M))
        assert set(images) == {"SONARQUBE_IMAGE", "SCANNER_IMAGE"}
        for image in images.values():
            assert re.fullmatch(r"[\w./-]+@sha256:[0-9a-f]{64}", image), image

    def test_the_server_it_starts_keeps_its_data_on_tmpfs(self) -> None:
        text = _GATE.read_text(encoding="utf-8")
        assert "--tmpfs /opt/sonarqube/data:size=6g,uid=1000,gid=0,mode=0775" in text
        assert "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true" in text
        assert 'rm -f -v "$CONTAINER"' in text, "the container and its anonymous volumes go on exit"

    def test_without_docker_it_refuses_with_its_own_exit_status(self, tmp_path: Path) -> None:
        env = {**os.environ, "DOCKER": str(tmp_path / "no-docker-here")}
        # S603: fixed argv, no shell, test-controlled paths.
        result = subprocess.run(  # noqa: S603
            [_SH, str(_GATE), str(tmp_path)], env=env, capture_output=True, text=True, timeout=60, check=False,
        )
        assert result.returncode == 3
        assert "docker is not available" in result.stderr

    def test_it_is_posix_sh(self) -> None:
        text = _GATE.read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n")
        assert "[[" not in text and "function " not in text


class TestThePackagerRunsIt:
    def _text(self) -> str:
        return _repo_only("scripts/package-appstore.sh").read_text(encoding="utf-8")

    def test_the_gate_runs_on_the_stage_after_the_fast_pre_check_and_before_the_zip(self) -> None:
        text = self._text()
        run = text.index('sh scripts/sonar-gate.sh "$STAGE"')
        assert text.index('python3 scripts/sonar_rules.py "${SONAR_BASE') < run < text.index("# ── Build")
        assert "exit 1" in text[run:text.index("# ── Build")]

    def test_skip_sonar_gate_is_the_only_override_and_it_is_recorded(self) -> None:
        text = self._text()
        assert set(re.findall(r"\b\w*SKIP\w*SONAR\w*|\bSONAR\w*SKIP\w*", text)) == {"SKIP_SONAR_GATE"}
        assert "SONAR GATE SKIPPED" in text[text.index("# ── Integrity record"):]

    def test_no_docker_is_named_as_the_reason(self) -> None:
        assert "docker is not available" in self._text()


class TestCiRunsIt:
    def _ci(self) -> dict[str, Any]:
        return yaml.safe_load(_repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8"))

    def test_a_job_runs_the_gate_on_every_push_and_pull_request(self) -> None:
        job = self._ci()["jobs"]["sonarqube"]
        assert "if" not in job, "the gate is the whole codebase, so it runs on master pushes too"
        assert job["timeout-minutes"] <= 60
        runs = "\n".join(step.get("run", "") for step in job["steps"])
        assert "sh scripts/sonar-gate.sh" in runs
        assert "SPECTRE_SONAR_TESTS: require" in _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")

    def test_the_existing_jobs_are_all_still_there(self) -> None:
        assert {"lint", "test", "test-postgres", "sast", "sca", "secrets", "container", "quality"} <= set(
            self._ci()["jobs"],
        )
