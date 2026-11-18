#!/usr/bin/env python3
"""The SonarQube half of scripts/sonar-gate.sh: talk to the server, read the verdict.

scripts/sonar-gate.sh owns the containers; this owns the HTTP. It is standard
library only, so it runs wherever the packager runs, and every secret it handles
comes from, and goes to, a file the shell created with mode 0600. Nothing here
prints a password or a token.

Subcommands, in the order the gate runs them:

  wait-up      poll /api/system/status until the server reports UP
  bootstrap    fresh server: replace admin/admin with a random password and mint
               a token; reused server: read the credentials given and mint a
               temporary token. Both land in the secrets file.
  prepare      recreate the project, build the quality profile from
               scripts/sonar-profile.json and bind the project to it
  wait-task    wait for the server to finish processing the analysis
  report       read every open issue and every unreviewed hotspot, print them,
               write the JSON report, exit 1 if there is even one
  revoke       revoke the temporary token minted for a reused server

The parsing functions (component_path, findings_from_issues and the rest) are
pure, so tests/unit/test_sonar_gate.py checks them without a server.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PAGE_SIZE = 500
#: The issue search refuses to page past 10,000 results; a tree that far gone
#: fails the gate on the first page anyway, so the cap is reported, not hidden.
SEARCH_CAP = 10_000

#: Folders and files the NOSONAR count skips: they are not analysed.
_SKIP_DIRS = frozenset({".git", "__pycache__", ".scannerwork", "node_modules"})
_TEXT_SUFFIXES = frozenset({".py", ".js", ".css", ".html", ".jinja", ".j2"})


class GateError(RuntimeError):
    """The gate could not reach a verdict. Distinct from a verdict of 'issues found'."""


# ── Pure functions: profile, findings, report ────────────────────────────────


@dataclass(frozen=True)
class Finding:
    """One open issue or one unreviewed hotspot, in the shape of the report."""

    kind: str  # "issue" or "hotspot"
    file: str
    line: int
    rule: str
    type: str
    severity: str
    message: str

    def as_line(self) -> str:
        """``file:line rule message``, the form the gate prints."""
        return f"{self.file}:{self.line} {self.rule} {self.message}"


def load_profile(path: Path) -> dict[str, Any]:
    """Read and validate scripts/sonar-profile.json; raise GateError if malformed."""
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"cannot read the quality profile {path}: {exc}") from exc
    problems = profile_problems(profile)
    if problems:
        raise GateError(f"{path} is malformed: " + "; ".join(problems))
    return dict(profile)


#: The rule repository each language's rules must come from.
_REPOSITORIES = {"py": ("python",), "js": ("javascript",), "css": ("css",), "web": ("Web",)}


def profile_problems(profile: Any) -> list[str]:
    """Every way *profile* departs from the shape the gate needs. Empty means well formed."""
    if not isinstance(profile, dict):
        return ["the top level is not an object"]
    problems: list[str] = []
    if not isinstance(profile.get("name"), str) or not profile["name"].strip():
        problems.append("no profile name")
    languages = profile.get("languages")
    if not isinstance(languages, dict) or set(languages) != set(_REPOSITORIES):
        return [*problems, f"languages must be exactly {sorted(_REPOSITORIES)}"]
    for language, spec in languages.items():
        problems.extend(_language_problems(language, spec))
    unavailable = profile.get("not_in_community_build", {})
    if not isinstance(unavailable, dict) or not all(
        isinstance(reason, str) and reason.strip() for reason in unavailable.values()
    ):
        problems.append("not_in_community_build must map each rule to a reason")
    return problems


def _language_problems(language: str, spec: Any) -> list[str]:
    if not isinstance(spec, dict):
        return [f"{language}: not an object"]
    problems: list[str] = []
    if not isinstance(spec.get("base"), str) or not spec["base"].strip():
        problems.append(f"{language}: no base profile")
    rules = spec.get("rules")
    if not isinstance(rules, list) or not rules:
        return [*problems, f"{language}: no rules"]
    if len(set(rules)) != len(rules):
        problems.append(f"{language}: a rule is listed twice")
    for rule in rules:
        repository = rule.split(":", 1)[0] if isinstance(rule, str) and ":" in rule else None
        if repository not in _REPOSITORIES[language]:
            problems.append(f"{language}: {rule!r} is not a {language} rule key")
    return problems


def profile_rules(profile: dict[str, Any]) -> set[str]:
    """Every rule key the profile names explicitly, across languages."""
    return {rule for spec in profile["languages"].values() for rule in spec["rules"]}


def component_path(component: str, project_key: str) -> str:
    """``spectre-gate:spectre/web/app.py`` to ``spectre/web/app.py``."""
    prefix = f"{project_key}:"
    return component[len(prefix):] if component.startswith(prefix) else component


def findings_from_issues(pages: list[dict[str, Any]], project_key: str) -> list[Finding]:
    """Open issues from /api/issues/search pages. A file-level issue has line 0."""
    return [
        Finding(
            kind="issue",
            file=component_path(issue.get("component", ""), project_key),
            line=int(issue.get("line") or 0),
            rule=issue.get("rule", "?"),
            type=issue.get("type", "?"),
            severity=issue.get("severity", "?"),
            message=" ".join(str(issue.get("message", "")).split()),
        )
        for page in pages
        for issue in page.get("issues", [])
    ]


def findings_from_hotspots(pages: list[dict[str, Any]], project_key: str) -> list[Finding]:
    """Unreviewed hotspots from /api/hotspots/search pages."""
    return [
        Finding(
            kind="hotspot",
            file=component_path(hotspot.get("component", ""), project_key),
            line=int(hotspot.get("line") or 0),
            rule=hotspot.get("ruleKey", "?"),
            type="SECURITY_HOTSPOT",
            severity=hotspot.get("vulnerabilityProbability", "?"),
            message=" ".join(str(hotspot.get("message", "")).split()),
        )
        for page in pages
        for hotspot in page.get("hotspots", [])
    ]


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))


def build_report(
    project_key: str,
    issues: list[Finding],
    hotspots: list[Finding],
    *,
    server_version: str = "",
    profile_sha256: str = "",
    suppressions: list[str] | None = None,
) -> dict[str, Any]:
    """The JSON report. ``issues`` uses the field names of the platform export."""

    def rows(findings: list[Finding]) -> list[dict[str, Any]]:
        return [{k: v for k, v in asdict(f).items() if k != "kind"} for f in sort_findings(findings)]

    by_rule: dict[str, int] = {}
    for finding in [*issues, *hotspots]:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
    return {
        "project": project_key,
        "server_version": server_version,
        "profile_sha256": profile_sha256,
        "verdict": "PASS" if not issues and not hotspots else "FAIL",
        "counts": {"issues": len(issues), "hotspots_to_review": len(hotspots), "by_rule": dict(sorted(by_rule.items()))},
        "issues": rows(issues),
        "hotspots": rows(hotspots),
        "suppressions": suppressions or [],
    }


def nosonar_lines(root: Path) -> list[str]:
    """Every ``NOSONAR`` marker in analysed text files, as ``file:line``.

    A suppression hides an issue from the server, so the gate cannot count it
    as one. It lists them instead, so a reader of the report sees each one.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        if _SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        found.extend(f"{relative}:{n}" for n, line in enumerate(text.splitlines(), 1) if "NOSONAR" in line)
    return found


def read_report_task(path: Path) -> str:
    """The ceTaskId the scanner wrote to report-task.txt."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"the scanner left no report-task.txt ({exc}); did the analysis run?") from exc
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "ceTaskId" and value.strip():
            return value.strip()
    raise GateError(f"{path} names no ceTaskId")


def generate_password() -> str:
    """A random admin password that meets SonarQube's complexity rule.

    26.x asks for 12 or more characters with an upper case letter, a lower case
    letter, a digit and a special character. The fixed tail guarantees one of
    each; the random head carries the entropy.
    """
    return secrets.token_urlsafe(30) + "#Aa1"


def parse_credentials(text: str) -> dict[str, str]:
    """A credentials file: the JSON this script writes, ``user:password``, or a bare token."""
    text = text.strip()
    if not text:
        raise GateError("the credentials file is empty")
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise GateError("the credentials file is not valid JSON") from exc
        if not isinstance(data, dict) or not data.get("auth"):
            raise GateError("the credentials file names no 'auth'")
        return {k: str(v) for k, v in data.items()}
    if ":" in text:
        return {"auth": text}
    return {"auth": f"{text}:", "token": text}


# ── The server ───────────────────────────────────────────────────────────────


class Sonar:
    """A minimal SonarQube Web API client. Credentials never reach a message."""

    def __init__(self, host: str, auth: str | None = None) -> None:
        self.host = host.rstrip("/")
        self._auth = auth

    def call(self, method: str, path: str, params: dict[str, Any] | None = None, *, missing_ok: bool = False) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.host}{path}"
        data = None
        if method == "GET" and query:
            url = f"{url}?{query}"
        elif query:
            data = query.encode()
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - the host is the gate's own server
        if self._auth:
            request.add_header("Authorization", "Basic " + base64.b64encode(self._auth.encode()).decode())
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - as above
                body = response.read()
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise GateError(f"{method} {path} answered {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GateError(f"{method} {path} failed: {exc}") from exc
        return json.loads(body) if body.strip() else None

    def pages(self, path: str, params: dict[str, Any], key: str) -> list[dict[str, Any]]:
        """Every page of a paged search, stopping at the server's own cap."""
        collected: list[dict[str, Any]] = []
        page = 1
        while True:
            body = self.call("GET", path, {**params, "ps": PAGE_SIZE, "p": page})
            collected.append(body)
            total = int(body.get("paging", {}).get("total", body.get("total", 0)))
            if page * PAGE_SIZE >= min(total, SEARCH_CAP) or not body.get(key):
                return collected
            page += 1


def _secrets_in(path: Path) -> dict[str, str]:
    return parse_credentials(path.read_text(encoding="utf-8"))


def _write_secrets(path: Path, values: dict[str, str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(values, handle)
    os.chmod(path, 0o600)


def _client(args: argparse.Namespace) -> Sonar:
    return Sonar(args.host, _secrets_in(Path(args.secrets))["auth"])


def cmd_wait_up(args: argparse.Namespace) -> int:
    sonar = Sonar(args.host)
    deadline = time.monotonic() + args.timeout
    status = "unreachable"
    while time.monotonic() < deadline:
        try:
            status = sonar.call("GET", "/api/system/status").get("status", "?")
        except GateError:
            status = "unreachable"
        if status == "UP":
            return 0
        if args.once:
            return 1
        time.sleep(3)
    print(f"  SonarQube at {args.host} did not come UP within {args.timeout}s (last status: {status})")
    return 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    out = Path(args.secrets)
    token_name = f"spectre-gate-{secrets.token_hex(6)}"
    if args.fresh:
        fresh = Sonar(args.host, "admin:admin")
        if not fresh.call("GET", "/api/authentication/validate").get("valid"):
            raise GateError("the server this gate started does not accept the default admin login")
        password = generate_password()
        fresh.call("POST", "/api/users/change_password",
                   {"login": "admin", "previousPassword": "admin", "password": password})
        values = {"auth": f"admin:{password}"}
    else:
        values = parse_credentials(Path(args.auth_file).read_text(encoding="utf-8"))
    sonar = Sonar(args.host, values["auth"])
    if not sonar.call("GET", "/api/authentication/validate").get("valid"):
        raise GateError(f"the credentials given are not valid on {args.host}")
    if not values.get("token"):
        values["token"] = sonar.call("POST", "/api/user_tokens/generate", {"name": token_name})["token"]
        values["temporary_token"] = token_name
    _write_secrets(out, values)
    print("  credentials ready (held in a private temporary file, never printed)")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    values = _secrets_in(Path(args.secrets))
    if values.get("temporary_token"):
        Sonar(args.host, values["auth"]).call("POST", "/api/user_tokens/revoke", {"name": values["temporary_token"]})
    return 0


def _active_rules(sonar: Sonar, profile_key: str) -> set[str]:
    pages = sonar.pages("/api/rules/search", {"qprofile": profile_key, "activation": "true", "f": "name"}, "rules")
    return {rule["key"] for page in pages for rule in page.get("rules", [])}


def _profiles_by_name(sonar: Sonar, language: str) -> dict[str, dict[str, Any]]:
    profiles = sonar.call("GET", "/api/qualityprofiles/search", {"language": language})["profiles"]
    return {p["name"]: p for p in profiles}


def _unknown_rules(sonar: Sonar, rules: list[str], unavailable: dict[str, str]) -> list[str]:
    return [
        rule for rule in rules
        if rule not in unavailable and sonar.call("GET", "/api/rules/show", {"key": rule}, missing_ok=True) is None
    ]


def _prepare_language(sonar: Sonar, name: str, language: str, spec: dict[str, Any], unavailable: dict[str, str]) -> str:
    profiles = _profiles_by_name(sonar, language)
    base = profiles.get(spec["base"])
    if base is None:
        raise GateError(f"{language}: the base profile {spec['base']!r} is not on this server; "
                        f"it offers {sorted(profiles)}")
    unknown = _unknown_rules(sonar, spec["rules"], unavailable)
    if unknown:
        raise GateError(f"{language}: this server does not know {unknown}. A rule the gate cannot run "
                        "must be listed, with a reason, under not_in_community_build.")
    target = profiles.get(name)
    if target is None:
        key = sonar.call("POST", "/api/qualityprofiles/copy", {"fromKey": base["key"], "toName": name})["key"]
    elif target.get("isBuiltIn"):
        raise GateError(f"{language}: {name!r} is a built-in profile name; choose another")
    else:
        key = target["key"]
    expected = _active_rules(sonar, base["key"]) | set(spec["rules"])
    for rule in sorted(expected - _active_rules(sonar, key)):
        sonar.call("POST", "/api/qualityprofiles/activate_rule", {"key": key, "rule": rule})
    active = _active_rules(sonar, key)
    if not expected <= active:
        raise GateError(f"{language}: these rules would not activate: {sorted(expected - active)}")
    return f"{language}: {name} = {spec['base']} and {len(spec['rules'])} named rules, {len(active)} active"


def cmd_prepare(args: argparse.Namespace) -> int:
    profile = load_profile(Path(args.profile))
    sonar = _client(args)
    name = profile["name"]
    unavailable = profile.get("not_in_community_build", {})
    # A fresh project every run: a resolution made by hand in the UI on an
    # earlier analysis (won't fix, false positive, safe) cannot carry over and
    # quietly pass the gate. The code is the only place a finding can be settled.
    sonar.call("POST", "/api/projects/delete", {"project": args.project}, missing_ok=True)
    sonar.call("POST", "/api/projects/create", {"project": args.project, "name": f"SPECTRE ({args.project})"})
    for language, spec in profile["languages"].items():
        print("  " + _prepare_language(sonar, name, language, spec, unavailable))
        sonar.call("POST", "/api/qualityprofiles/add_project",
                   {"language": language, "qualityProfile": name, "project": args.project})
        if args.set_default:
            sonar.call("POST", "/api/qualityprofiles/set_default", {"language": language, "qualityProfile": name})
    for rule, reason in unavailable.items():
        print(f"  NOT RUN {rule}: {reason}")
    return 0


def cmd_wait_task(args: argparse.Namespace) -> int:
    sonar = _client(args)
    task_id = read_report_task(Path(args.report_task))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        task = sonar.call("GET", "/api/ce/task", {"id": task_id})["task"]
        status = task.get("status")
        if status == "SUCCESS":
            return 0
        if status in {"FAILED", "CANCELED"}:
            raise GateError(f"the server could not process the analysis: {status} {task.get('errorMessage', '')}")
        time.sleep(2)
    raise GateError(f"the analysis was not processed within {args.timeout}s")


def cmd_report(args: argparse.Namespace) -> int:
    sonar = _client(args)
    issue_pages = sonar.pages("/api/issues/search", {"componentKeys": args.project, "resolved": "false"}, "issues")
    hotspot_pages = sonar.pages("/api/hotspots/search", {"project": args.project, "status": "TO_REVIEW"}, "hotspots")
    issues = findings_from_issues(issue_pages, args.project)
    hotspots = findings_from_hotspots(hotspot_pages, args.project)
    version = _server_version(args.host)
    profile_sha = hashlib.sha256(Path(args.profile).read_bytes()).hexdigest() if args.profile else ""
    report = build_report(
        args.project, issues, hotspots, server_version=version, profile_sha256=profile_sha,
        suppressions=nosonar_lines(Path(args.target)) if args.target else [],
    )
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for finding in sort_findings(issues):
        print(finding.as_line())
    for finding in sort_findings(hotspots):
        print(f"{finding.as_line()} [security hotspot, not reviewed]")
    counts = report["counts"]
    print(f"\n  {counts['issues']} open issues, {counts['hotspots_to_review']} security hotspots to review")
    for rule, count in counts["by_rule"].items():
        print(f"    {count:4d}  {rule}")
    if report["suppressions"]:
        print(f"  {len(report['suppressions'])} NOSONAR suppressions in the tree (listed in the report)")
    return 0 if report["verdict"] == "PASS" else 1


def _server_version(host: str) -> str:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/server/version", timeout=30) as response:  # noqa: S310 - the gate's own server
            return str(response.read().decode("utf-8", "replace")).strip()
    except (urllib.error.URLError, OSError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, *, needs_secrets: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        p.add_argument("--host", required=True)
        if needs_secrets:
            p.add_argument("--secrets", required=True, help="the private credentials file")
        return p

    p = command("wait-up", needs_secrets=False)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--once", action="store_true", help="one probe: exit 0 if UP now")
    p.set_defaults(func=cmd_wait_up)

    p = command("bootstrap")
    p.add_argument("--fresh", action="store_true", help="this gate started the server")
    p.add_argument("--auth-file", help="credentials for a server this gate did not start")
    p.set_defaults(func=cmd_bootstrap)

    p = command("prepare")
    p.add_argument("--profile", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--set-default", action="store_true")
    p.set_defaults(func=cmd_prepare)

    p = command("wait-task")
    p.add_argument("--report-task", required=True)
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_wait_task)

    p = command("report")
    p.add_argument("--project", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--profile", default="")
    p.add_argument("--target", default="", help="the scanned tree, to list NOSONAR markers")
    p.set_defaults(func=cmd_report)

    p = command("revoke")
    p.set_defaults(func=cmd_revoke)

    args = parser.parse_args(argv)
    if args.command == "bootstrap" and not args.fresh and not args.auth_file:
        parser.error("bootstrap needs --fresh or --auth-file")
    try:
        return int(args.func(args))
    except GateError as exc:
        print(f"  GATE ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
