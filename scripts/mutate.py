#!/usr/bin/env python3
"""Mutation testing runner for SPECTRE, with no dependency beyond the dev set.

WHY

Coverage says a line ran. It does not say a test would notice the line being
wrong. The audit's mutation sample (audit/working/tools/mutate.py) showed the
gap with 21 hand-written mutants; this runner makes the same check repeatable
and complete over a module: every mutant the operators below can make is
generated, run against the tests that cover its line, and recorded.

HOW

1. ``map`` runs pytest under coverage with per-test contexts, so the runner
   knows which tests execute each line, and writes a JUnit file so it knows how
   long each test takes. Run it once per test directory; results accumulate.
2. ``run`` generates the mutants for the named files and runs each one in a
   forked child. The child serves the mutated source from memory through an
   import hook, so nothing on disk changes and several mutants run at once in
   one working tree. Third-party packages are imported once in the parent
   before forking, which removes most of pytest's start-up cost per mutant.
   Covering tests run fastest first and stop at the first failure. A mutant
   that survives the quick pass is run again against every covering test
   before it is recorded as a survivor. A kill counts only once the tests
   that ran, up to and including the one that failed, pass on the unmutated
   code: a test that leans on an earlier test the mutant's run left out fails
   whatever the mutant does. Where they do not pass, the mutant is run again
   against its covering test files whole. A kill then counts only if the
   killing test, run by itself against the mutant, still fails: one that
   passes alone failed because of what an earlier test in the run left
   behind, an order-dependent false kill, and the mutant is recorded as a
   survivor. Rechecking a kill an older runner recorded (``--retest-killer``)
   starts with its killer alone, against the mutant and then the unmutated
   code, and falls back to a full run only if either answer is wrong.
   Results append to ``results.jsonl``, so a run can stop at its time budget and resume where it
   left off.
3. ``report`` prints the per-module totals and the survivors as Markdown.

OPERATORS

Arithmetic (+ -, * /, // /, ** *, % *), augmented assignment, comparison
(< <=, > >=, == !=, is / is not, in / not in), boolean (and or), removal of
``not`` and of unary minus, integer n to n + 1, float 0.0 to 1.0 and f to
1.5 f, True and False swapped, ``return x`` to ``return None``, a bare call
statement to ``pass``, and (with ``--strings``) a string s to "XX" s "XX".

Not mutated, each for a stated reason: docstrings and annotations (no runtime
behaviour), f-strings and logging calls (message text; log line safety is
tested where it is enforced, in log_safety.py), code under ``TYPE_CHECKING``,
``__all__``, and any line carrying ``pragma: no mutate``.

Usage:
    python scripts/mutate.py map --state DIR --target spectre/web/auth.py ... tests/unit
    python scripts/mutate.py run --state DIR [--jobs 4] [--budget 540] [--strings] FILE ...
    python scripts/mutate.py report --state DIR FILE ...
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import dataclasses
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Raised when a change to the runner could have produced false kills, so a
#: kill recorded by an older runner can be confirmed (--retest-killer).
HARNESS = 4

_LOG_NAMES = {"logger", "log", "logging", "_log", "_logger", "LOGGER"}
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}

_BINOP_SWAP: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div, ast.Pow: ast.Mult, ast.Mod: ast.Mult,
    ast.BitAnd: ast.BitOr, ast.BitOr: ast.BitAnd,
}
_CMP_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}


@dataclasses.dataclass(frozen=True)
class Mutant:
    """One single-point change to one file."""

    path: str
    line: int
    end_line: int
    start: int  # byte offset into the file
    end: int
    replacement: str
    operator: str
    original: str

    @property
    def ident(self) -> str:
        digest = hashlib.sha256(f"{self.start}:{self.end}:{self.replacement}".encode()).hexdigest()[:10]
        return f"{self.path}:{self.line}:{self.operator}:{digest}"

    def apply(self, source: bytes) -> bytes:
        return source[: self.start] + self.replacement.encode() + source[self.end :]

    def describe(self) -> str:
        old = " ".join(self.original.split())
        new = " ".join(self.replacement.split())
        return f"{old[:70]} -> {new[:70]}"


# ── Mutant generation ────────────────────────────────────────────────────────


def _is_log_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    owner = node.func.value
    return isinstance(owner, ast.Name) and owner.id in _LOG_NAMES and node.func.attr in _LOG_METHODS


def _excluded_nodes(tree: ast.Module) -> set[int]:
    """ids of every node a mutant must not touch."""
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                roots.append(first)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            roots.extend(a.annotation for a in (*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs) if a.annotation)
            for extra in (node.args.vararg, node.args.kwarg):
                if extra is not None and extra.annotation is not None:
                    roots.append(extra.annotation)
            if node.returns is not None:
                roots.append(node.returns)
        if isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        if isinstance(node, ast.JoinedStr) or _is_log_call(node):
            roots.append(node)
        if isinstance(node, ast.Expr) and _is_log_call(node.value):
            roots.append(node)
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            roots.append(node)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            roots.append(node)
    excluded: set[int] = set()
    for root in roots:
        excluded.update(id(n) for n in ast.walk(root))
    return excluded


def _message_strings(tree: ast.Module) -> set[int]:
    """ids of string constants that are only message text: raise arguments and detail=."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            found.update(id(n) for n in ast.walk(node.exc) if isinstance(n, ast.Constant))
        if isinstance(node, ast.keyword) and node.arg == "detail":
            found.update(id(n) for n in ast.walk(node.value) if isinstance(n, ast.Constant))
    return found


class _Offsets:
    def __init__(self, source: bytes) -> None:
        self.starts = [0]
        for index, byte in enumerate(source):
            if byte == 0x0A:
                self.starts.append(index + 1)

    def span(self, node: ast.AST) -> tuple[int, int]:
        start = self.starts[node.lineno - 1] + node.col_offset  # type: ignore[attr-defined]
        end = self.starts[node.end_lineno - 1] + node.end_col_offset  # type: ignore[attr-defined]
        return start, end


def _float_mutant(value: float) -> float:
    return 1.0 if value == 0.0 else value * 1.5


def _expression_mutants(node: ast.AST, strings: bool, messages: set[int]) -> Iterator[tuple[str, ast.AST | str]]:
    """(operator name, replacement node or text) for one expression node."""
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOP_SWAP:
        swapped = copy.copy(node)
        swapped.op = _BINOP_SWAP[type(node.op)]()
        yield "binop", swapped
    elif isinstance(node, ast.Compare):
        for index, op in enumerate(node.ops):
            if type(op) in _CMP_SWAP:
                changed = copy.copy(node)
                changed.ops = [*node.ops]
                changed.ops[index] = _CMP_SWAP[type(op)]()
                yield "compare", changed
    elif isinstance(node, ast.BoolOp):
        flipped = copy.copy(node)
        flipped.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        yield "boolop", flipped
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub)):
        yield "unary", node.operand
    elif isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            yield "bool", ast.Constant(not value)
        elif isinstance(value, int):
            yield "number", ast.Constant(value + 1)
        elif isinstance(value, float):
            yield "number", ast.Constant(_float_mutant(value))
        elif strings and isinstance(value, str) and id(node) not in messages:
            yield "string", ast.Constant(f"XX{value}XX")


def generate(path: str, strings: bool = False) -> list[Mutant]:
    """Every mutant the operators make for the file at *path* (relative to ROOT)."""
    source = (ROOT / path).read_bytes()
    tree = ast.parse(source)
    lines = source.decode().splitlines()
    excluded = _excluded_nodes(tree)
    messages = _message_strings(tree)
    offsets = _Offsets(source)
    mutants: list[Mutant] = []

    def add(node: ast.AST, operator: str, replacement: ast.AST | str) -> None:
        if "pragma: no mutate" in lines[node.lineno - 1]:  # type: ignore[attr-defined]
            return
        start, end = offsets.span(node)
        text = replacement if isinstance(replacement, str) else f"({ast.unparse(replacement)})"
        original = source[start:end].decode()
        if text.strip("()") == original:
            return
        mutants.append(Mutant(path, node.lineno, node.end_lineno, start, end, text, operator, original))  # type: ignore[attr-defined]

    for node in ast.walk(tree):
        if id(node) in excluded or not hasattr(node, "lineno"):
            continue
        if isinstance(node, ast.expr):
            if isinstance(getattr(node, "ctx", ast.Load()), (ast.Store, ast.Del)):
                continue
            for operator, replacement in _expression_mutants(node, strings, messages):
                add(node, operator, replacement)
        elif isinstance(node, ast.AugAssign) and type(node.op) in _BINOP_SWAP:
            changed = copy.copy(node)
            changed.op = _BINOP_SWAP[type(node.op)]()
            add(node, "augassign", ast.unparse(changed))
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                add(node, "return", "return None")
        elif isinstance(node, ast.Expr) and isinstance(node.value, (ast.Call, ast.Await)):
            add(node, "call", "pass")
    mutants.sort(key=lambda m: (m.start, m.end, m.operator, m.replacement))
    return mutants


# ── Coverage map ─────────────────────────────────────────────────────────────


def _module_name(path: str) -> str:
    return path[: -len(".py")].replace("/", ".").removesuffix(".__init__")


def cmd_map(args: argparse.Namespace) -> int:
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    slug = hashlib.sha256(" ".join(args.tests).encode()).hexdigest()[:8]
    cov_args = [f"--cov={t}" for t in args.target]
    env = dict(os.environ, COVERAGE_FILE=str(state.resolve() / ".coverage"))
    command = [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "-W", "ignore",
        *cov_args, "--cov-context=test", "--cov-report=", "--cov-append", "--cov-fail-under=0",
        f"--junitxml={state.resolve() / f'junit-{slug}.xml'}", *args.tests,
    ]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode  # noqa: S603


def _node_from_context(context: str) -> str:
    return context.rsplit("|", 1)[0]


def _junit_key(nodeid: str) -> tuple[str, str]:
    file_part, _, rest = nodeid.partition("::")
    parts = rest.split("::")
    classname = ".".join([file_part[: -len(".py")].replace("/", "."), *parts[:-1]])
    return classname, parts[-1]


def load_durations(state: Path) -> dict[tuple[str, str], tuple[float, int]]:
    """(seconds, position in the run) for every test the map recorded."""
    durations: dict[tuple[str, str], tuple[float, int]] = {}
    for junit in sorted(state.glob("junit-*.xml")):
        for case in ET.parse(junit).getroot().iter("testcase"):  # noqa: S314 - our own pytest output
            key = (case.get("classname", ""), case.get("name", ""))
            durations[key] = (float(case.get("time", "0") or 0), len(durations))
    return durations


def load_line_map(state: Path, path: str) -> dict[int, set[str]]:
    from coverage import CoverageData

    data = CoverageData(basename=str(state / ".coverage"))
    data.read()
    absolute = str(ROOT / path)
    measured = next((f for f in data.measured_files() if os.path.realpath(f) == os.path.realpath(absolute)), None)
    if measured is None:
        return {}
    by_line = data.contexts_by_lineno(measured)
    line_map = {line: {_node_from_context(c) for c in contexts if c} for line, contexts in by_line.items()}
    # A line outside every function body runs once, at import, and coverage
    # files it under whichever test happened to import the module first. Every
    # test that reaches the module depends on it.
    everyone = set().union(*line_map.values()) if line_map else set()
    # A test that reads such a value but runs nothing else in the module is
    # not in that set, so every test file that imports the module joins it.
    files = set(_importing_files(path))
    everyone = {t for t in everyone if t.split("::")[0] not in files} | files
    runtime = _function_body_lines(path)
    for line in line_map:
        if line not in runtime:
            line_map[line] = everyone
    return line_map


def _importing_files(path: str) -> list[str]:
    """Test files that import the module at *path* by name."""
    dotted = _module_name(path)
    package, _, stem = dotted.rpartition(".")
    pattern = re.compile(rf"\b{re.escape(dotted)}\b|from {re.escape(package)} import [^\n]*\b{re.escape(stem)}\b")
    return sorted(str(f.relative_to(ROOT)) for f in (ROOT / "tests").rglob("test_*.py") if pattern.search(f.read_text()))


def _function_body_lines(path: str) -> set[int]:
    """Lines inside a function body: they run when called, not at import."""
    lines: set[int] = set()
    for node in ast.walk(ast.parse((ROOT / path).read_bytes())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.update(range(node.body[0].lineno, node.end_lineno + 1))  # type: ignore[operator]
        elif isinstance(node, ast.Lambda):
            lines.update(range(node.body.lineno, node.body.end_lineno + 1))  # type: ignore[operator]
    return lines


# ── Running mutants ──────────────────────────────────────────────────────────


class _MutantFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves one module's mutated source from memory."""

    def __init__(self, module: str, filename: str, source: bytes) -> None:
        self.module = module
        self.filename = filename
        self.source = source

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> importlib.machinery.ModuleSpec | None:
        if fullname != self.module:
            return None
        is_package = self.filename.endswith("__init__.py")
        spec = importlib.util.spec_from_loader(fullname, self, origin=self.filename, is_package=is_package)
        if spec is not None:
            spec.has_location = True
            if is_package:
                spec.submodule_search_locations = [str(Path(self.filename).parent)]
        return spec

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: object) -> None:
        module.__file__ = self.filename  # type: ignore[attr-defined]
        code = compile(self.source, self.filename, "exec", dont_inherit=True)
        exec(code, vars(module))  # noqa: S102 - the mutant under test


class _FirstFailure:
    def __init__(self) -> None:
        self.nodeid = ""

    def pytest_runtest_logreport(self, report: object) -> None:
        if getattr(report, "failed", False) and not self.nodeid:
            self.nodeid = str(getattr(report, "nodeid", ""))


def _child(mutant: Mutant, tests: list[str], out: Path) -> None:
    """Runs in the forked child: never returns."""
    code = 3
    # Every child gets directories of its own. The app writes a probe file into
    # its SQLite directory at start-up, under a fixed name in ./data unless told
    # otherwise, and two children starting the app together raced on it: the
    # loser failed a test the mutant had nothing to do with, a false kill.
    scratch = tempfile.mkdtemp(prefix="spectre-mutant-")
    for name in ("SPECTRE_SQLITE_DIR", "SPECTRE_DATA_DIR", "TMPDIR"):
        os.environ[name] = os.path.join(scratch, name.lower())
        os.makedirs(os.environ[name])
    tempfile.tempdir = None
    try:
        log = os.open(str(out) + ".log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(log, 1)
        os.dup2(log, 2)
        source = mutant.apply((ROOT / mutant.path).read_bytes())
        try:
            compile(source, mutant.path, "exec", dont_inherit=True)
        except SyntaxError:
            out.write_text(json.dumps({"rc": -2, "killer": ""}))
            os._exit(0)
        sys.meta_path.insert(0, _MutantFinder(_module_name(mutant.path), str(ROOT / mutant.path), source))
        import pytest

        recorder = _FirstFailure()
        code = int(pytest.main(["-x", "-q", "-p", "no:cacheprovider", "-p", "no:cov", "-o", "addopts=", "-W", "ignore",
                                "--no-header", "-o", "console_output_style=classic", *tests], plugins=[recorder]))
        out.write_text(json.dumps({"rc": code, "killer": recorder.nodeid}))
    except BaseException as exc:  # noqa: BLE001 - the child must always exit
        with contextlib.suppress(OSError):
            out.write_text(json.dumps({"rc": 99, "killer": f"runner: {exc!r}"[:200]}))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        os._exit(code if code in (0, 1) else 0)


def _prewarm() -> None:
    """Import every third-party module the app and suite use, once, before forking."""
    probe = (
        "import sys, json, tests.conftest, tests.integration.conftest, spectre.web.app\n"
        "print(json.dumps(list(sys.modules)))  # import order, not sorted"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return
    ours = ("spectre", "tests", "tle_clustering", "__main__")
    for name in json.loads(result.stdout.strip().splitlines()[-1]):
        if name.split(".")[0] in ours:
            continue
        with contextlib.suppress(Exception):
            importlib.import_module(name)
    import pytest  # noqa: F401


def _order(
    tests: set[str], durations: dict[tuple[str, str], tuple[float, int]], stem: str | None = None,
) -> list[tuple[str, float]]:
    """Covering tests, the module's own test files first, then unit before integration, then cheapest file first,
    each file's tests in their own order.

    Ordered by test alone, tests from different modules interleave and a
    module-scoped fixture (the integration suite's app and event loop) is torn
    down and rebuilt mid-module, which fails the unmutated code.
    """
    timed = {t: durations.get(_junit_key(t), (1.0, 1 << 30)) for t in tests}
    by_file: dict[str, float] = {}
    for test, (seconds, _) in timed.items():
        by_file[test.split("::")[0]] = by_file.get(test.split("::")[0], 0.0) + seconds

    def rank(test: str) -> tuple[bool, bool, float, str, int]:
        file = test.split("::")[0]
        own = stem is not None and stem in Path(file).stem
        return (not own, not file.startswith("tests/unit/"), by_file[file], file, timed[test][1])

    return [(t, timed[t][0]) for t in sorted(timed, key=rank)]


def _quick(ordered: list[tuple[str, float]], cap: float) -> list[str]:
    chosen: list[str] = []
    spent = 0.0
    for test, seconds in ordered:
        if chosen and spent + seconds > cap:
            break
        chosen.append(test)
        spent += seconds
    return chosen


def _control_passes(path: str, state: Path, durations: dict[tuple[str, str], tuple[float, int]], work: Path, cap: float) -> bool:
    """Run the file's quick-pass tests on an unchanged copy served the same way as a mutant.

    A mutant only counts as killed if the unmutated code passes under the same
    harness, so a broken harness cannot report a perfect score. A pass is
    remembered against the file's content, so a resumed run does not repeat it.
    """
    source = (ROOT / path).read_bytes()
    stamp = state / "controls" / (hashlib.sha256(source).hexdigest() + ".passed")
    if stamp.exists():
        return True
    tests: set[str] = set().union(*load_line_map(state, path).values())
    if tests:
        null = Mutant(path, 1, 1, 0, 0, "", "control", "")
        out = work / f"control-{os.getpid()}.json"
        pid = os.fork()
        if pid == 0:
            _child(null, _quick(_order(tests, durations), cap), out)
        os.waitpid(pid, 0)
        try:
            passed = int(json.loads(out.read_text())["rc"]) == 0
        except (OSError, ValueError):
            passed = False
        finally:
            for leftover in (out, Path(str(out) + ".log")):
                with contextlib.suppress(OSError):
                    leftover.unlink()
        if not passed:
            return False
    stamp.parent.mkdir(exist_ok=True)
    stamp.write_text(path + "\n")
    return True


@dataclasses.dataclass
class _Job:
    mutant: Mutant
    tests: list[str]
    stage: str  # "alone" (a recorded killer by itself), "quick", "full", "capped", "files" (whole test
    # files), "confirm" (a kill's control) or "verify" (a kill's killer alone against the mutant)
    deadline: float
    out: Path
    started: float
    #: For a "confirm" or "verify" job: the run whose kill it checks, and the test that failed there.
    origin: _Job | None = None
    killer: str = ""


def _prefix(tests: list[str], killer: str) -> list[str]:
    """The tests a run with -x ran before *killer* failed, *killer* included.

    *tests* holds node ids or, in a "files" run, whole files. A killer that
    names neither (a parametrised id reported in full) gives the whole list.
    """
    for name in (killer, killer.split("::")[0]):
        if name in tests:
            return tests[: tests.index(name) + 1]
    return list(tests)


class _Runner:
    """Forks one child per mutant, up to *jobs* at a time, and records each outcome."""

    def __init__(self, args: argparse.Namespace, state: Path, ordered: dict[str, list[tuple[str, float]]],
                 killers: dict[str, str] | None = None) -> None:
        self.args = args
        #: Mutant id to the test an older runner recorded as killing it, tried alone first.
        self.killers = killers or {}
        self.work = state / "work"
        self.controls = state / "controls"
        self.controls.mkdir(exist_ok=True)
        self.results = state / "results.jsonl"
        self.ordered = ordered
        self.running: dict[int, _Job] = {}
        self.counter = 0
        self.stop_at = time.monotonic() + args.budget

    def _deadline(self, seconds: float) -> float:
        return time.monotonic() + float(self.args.timeout_floor) + float(self.args.timeout_factor) * seconds

    def record(self, job: _Job, status: str, killer: str, alone: bool = False) -> None:
        row = {"id": job.mutant.ident, "path": job.mutant.path, "line": job.mutant.line,
               "operator": job.mutant.operator, "change": job.mutant.describe(), "status": status,
               "killer": killer, "tests": len(job.tests), "stage": job.stage, "alone": alone,
               "seconds": round(time.monotonic() - job.started, 1), "harness": HARNESS}
        with self.results.open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def launch(self, mutant: Mutant, tests: list[str], stage: str, seconds: float,
               origin: _Job | None = None, killer: str = "") -> None:
        self.counter += 1
        out = self.work / f"{os.getpid()}-{self.counter}.json"
        pid = os.fork()
        if pid == 0:
            _child(mutant, tests, out)
        started = origin.started if origin is not None else time.monotonic()
        self.running[pid] = _Job(mutant, tests, stage, self._deadline(seconds), out, started, origin, killer)

    def _control_stamp(self, tests: list[str]) -> Path:
        return self.controls / hashlib.sha256("\n".join(tests).encode()).hexdigest()

    def confirm(self, job: _Job, killer: str) -> None:
        """Record *job*'s kill only if its tests up to *killer* pass on the unmutated code."""
        prefix = _prefix(job.tests, killer)
        stamp = self._control_stamp(prefix)
        if stamp.with_suffix(".prefix-passed").exists():
            self.verify(job, killer)
        elif stamp.with_suffix(".prefix-failed").exists():
            self.escalate(job, killer)
        else:
            null = Mutant(job.mutant.path, 1, 1, 0, 0, "", "control", "")
            self.launch(null, prefix, "confirm", job.deadline - job.started, origin=job, killer=killer)

    def escalate(self, job: _Job, killer: str) -> None:
        """A kill the unmutated code also fails: run the covering files whole, or give up on the mutant."""
        if job.stage == "alone":
            self.start(job.mutant)
            return
        if job.stage == "files":
            self.record(job, "error", f"order-dependent: {killer}")
            return
        ordered = self.ordered[job.mutant.ident]
        files = list(dict.fromkeys(t.split("::")[0] for t, _ in ordered))
        self.launch(job.mutant, files, "files", sum(s for _, s in ordered))

    def settle_control(self, job: _Job, rc: int) -> None:
        assert job.origin is not None
        stamp = self._control_stamp(job.tests)
        stamp.with_suffix(".prefix-passed" if rc == 0 else ".prefix-failed").write_text("\n".join(job.tests) + "\n")
        if rc == 0:
            self.verify(job.origin, job.killer)
        else:
            self.escalate(job.origin, job.killer)

    def verify(self, job: _Job, killer: str) -> None:
        """Record *job*'s kill only if *killer*, run alone against the mutant, still fails.

        A test that fails after the others in its run and passes by itself
        failed because of what they left behind, not because of the mutant.
        A killer that was the first test of its run has already run alone.
        """
        if job.stage == "alone" or _prefix(job.tests, killer) == [killer]:
            self.record(job, "killed", killer, alone=True)
            return
        seconds = dict(self.ordered.get(job.mutant.ident, [])).get(killer, 1.0)
        self.launch(job.mutant, [killer], "verify", seconds, origin=job, killer=killer)

    def settle_verify(self, job: _Job, rc: int) -> None:
        assert job.origin is not None
        if rc == 1:
            self.record(job.origin, "killed", job.killer, alone=True)
        elif rc == 0:
            self.record(job.origin, "survived", f"order-dependent: {job.killer} passes alone", alone=True)
        else:
            self.record(job.origin, "error", f"{job.killer} alone: pytest exit {rc}", alone=True)

    def start(self, mutant: Mutant) -> None:
        ordered = self.ordered[mutant.ident]
        killer = self.killers.pop(mutant.ident, "")
        if killer:
            self.launch(mutant, [killer], "alone", dict(ordered).get(killer, 1.0))
            return
        if not ordered:
            self.record(_Job(mutant, [], "full", 0.0, self.work / "none", time.monotonic()), "no_tests", "")
            return
        quick = _quick(ordered, self.args.quick_seconds)
        stage = "full" if len(quick) == len(ordered) else "quick"
        self.launch(mutant, quick, stage, sum(s for _, s in ordered[: len(quick)]))

    def settle(self, job: _Job, outcome: dict[str, object]) -> None:
        rc = int(str(outcome["rc"]))
        if job.stage == "confirm":
            self.settle_control(job, rc)
            return
        if job.stage == "verify":
            self.settle_verify(job, rc)
            return
        if job.stage == "alone":
            # Killed alone: confirm it. Anything else: the full run decides.
            if rc == 1:
                self.confirm(job, job.tests[0])
            else:
                self.start(job.mutant)
            return
        ordered = self.ordered[job.mutant.ident]
        if rc == -2:
            self.record(job, "invalid", "")
        elif rc == 4 and job.stage != "files":
            # A test module parametrised from the mutated values names different
            # tests, so the node ids no longer resolve: run the files whole.
            files = list(dict.fromkeys(t.split("::")[0] for t, _ in ordered))
            self.launch(job.mutant, files, "files", sum(s for _, s in ordered))
        elif rc == 0 and job.stage == "quick" and time.monotonic() >= self.stop_at:
            pass  # out of budget: left unrecorded, so the next run repeats it in full
        elif rc == 0 and job.stage == "quick":
            cap = self.args.full_seconds
            wide = _quick(ordered, cap) if cap > 0 else [t for t, _ in ordered]
            self.launch(job.mutant, wide, "full" if len(wide) == len(ordered) else "capped",
                        sum(s for _, s in ordered[: len(wide)]))
        elif rc == 0:
            self.record(job, "survived", "")
        elif rc == 1:
            self.confirm(job, str(outcome["killer"]))
        else:
            self.record(job, "error", str(outcome["killer"]) or f"pytest exit {rc}")

    def reap(self) -> bool:
        """Settle every finished or overdue child; True if any was."""
        reaped = False
        for pid, job in list(self.running.items()):
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited == 0 and time.monotonic() <= job.deadline:
                continue
            if waited == 0:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            del self.running[pid]
            reaped = True
            if waited == 0:
                if job.stage == "confirm":
                    # The unmutated code hung on the same tests: the kill proves nothing.
                    self.escalate(job.origin, job.killer)  # type: ignore[arg-type]
                elif job.stage == "verify":
                    # The killer alone hangs on the mutant: caught, by timeout.
                    self.record(job.origin, "timeout", job.killer, alone=True)  # type: ignore[arg-type]
                else:
                    self.record(job, "timeout", "")
                continue
            try:
                outcome = json.loads(job.out.read_text())
            except (OSError, ValueError):
                outcome = {"rc": 98, "killer": f"child exit status {status}"}
            self.settle(job, outcome)
            for leftover in (job.out, Path(str(job.out) + ".log")):
                with contextlib.suppress(OSError):
                    leftover.unlink()
        return reaped

    def run(self, queue: list[Mutant]) -> int:
        pending = list(reversed(queue))
        while pending or self.running:
            while pending and len(self.running) < self.args.jobs and time.monotonic() < self.stop_at:
                self.start(pending.pop())
            if not self.running:
                break
            if not self.reap():
                time.sleep(0.05)
        return len(pending)


def cmd_run(args: argparse.Namespace) -> int:
    state = Path(args.state).resolve()
    (state / "work").mkdir(parents=True, exist_ok=True)
    done = latest_results(state)
    retest = set(args.retest or [])
    killer_pattern = re.compile(args.retest_killer) if args.retest_killer else None
    only = set(Path(args.ids).read_text().split()) if args.ids else None
    durations = load_durations(state)
    queue: list[Mutant] = []
    ordered: dict[str, list[tuple[str, float]]] = {}
    killers: dict[str, str] = {}
    for path in args.files:
        line_map = load_line_map(state, path)
        for mutant in generate(path, strings=args.strings):
            if only is not None and mutant.ident not in only:
                continue
            previous = done.get(mutant.ident)
            if previous is not None and previous["status"] not in retest and not (
                killer_pattern and previous["status"] in ("killed", "timeout")
                and int(str(previous.get("harness", 1))) < HARNESS and killer_pattern.search(str(previous["killer"]))
            ):
                continue
            tests: set[str] = set()
            for line in range(mutant.line, mutant.end_line + 1):
                tests |= line_map.get(line, set())
            queue.append(mutant)
            ordered[mutant.ident] = _order(tests, durations, Path(path).stem)
            killer = str(previous.get("killer", "")) if previous is not None else ""
            # A module-level line's tests are whole files, so the killer may be named by its file.
            if killer_pattern and killer and (killer in tests or killer.split("::")[0] in tests):
                killers[mutant.ident] = killer
    print(f"{len(queue)} mutants to run", flush=True)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    _prewarm()
    for path in dict.fromkeys(m.path for m in queue):
        if not _control_passes(path, state, durations, state / "work", args.quick_seconds):
            print(f"the unmutated {path} fails its own covering tests under this runner; no result would mean anything")
            return 2
    left = _Runner(args, state, ordered, killers).run(queue)
    print(f"stopped with {left} mutants not started" if left else "all mutants run", flush=True)
    return 0


# ── Report ───────────────────────────────────────────────────────────────────


def latest_results(state: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    path = state / "results.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            rows[str(row["id"])] = row
    return rows


def cmd_report(args: argparse.Namespace) -> int:
    rows = latest_results(Path(args.state))
    print("| Module | Mutants | Killed | Timed out | Survived | No covering test | Invalid | Score |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    survivors: list[dict[str, object]] = []
    for path in args.files:
        idents = {m.ident for m in generate(path, strings=args.strings)}
        mine = [rows[i] for i in idents if i in rows]
        counts = {k: sum(1 for r in mine if r["status"] == k) for k in
                  ("killed", "timeout", "survived", "no_tests", "invalid", "error")}
        valid = len(mine) - counts["invalid"]
        caught = counts["killed"] + counts["timeout"]
        score = f"{100 * caught / valid:.1f}%" if valid else "n/a"
        print(f"| `{path}` | {valid} of {len(idents)} run | {counts['killed']} | {counts['timeout']} | "
              f"{counts['survived']} | {counts['no_tests']} | {counts['invalid']} | {score} |")
        survivors.extend(r for r in mine if r["status"] in ("survived", "no_tests", "error"))
    if args.survivors:
        print("\n| Mutant | Line | Operator | Change | Status |\n|---|---:|---|---|---|")
        for row in sorted(survivors, key=lambda r: (str(r["path"]), int(str(r["line"])))):
            change = str(row["change"]).replace("|", "\\|")
            status = str(row["status"])
            if str(row.get("killer", "")).startswith("order-dependent"):
                status += " (killed only after other tests)"
            print(f"| `{str(row['id']).rsplit(':', 1)[-1]}` | `{row['path']}:{row['line']}` | {row['operator']} | "
                  f"`{change}` | {status} |")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    mapping = sub.add_parser("map", help="record which tests cover which lines")
    mapping.add_argument("--state", required=True)
    mapping.add_argument("--target", action="append", required=True, help="a file or package to measure")
    mapping.add_argument("tests", nargs="+")
    running = sub.add_parser("run", help="run mutants until done or out of budget")
    running.add_argument("--state", required=True)
    running.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    running.add_argument("--budget", type=float, default=540.0, help="seconds before no new mutant starts")
    running.add_argument("--quick-seconds", type=float, default=4.0, help="test time in the quick pass")
    running.add_argument("--full-seconds", type=float, default=0.0,
                         help="cap on the test time a quick-pass survivor is rerun against; 0 runs every covering test")
    running.add_argument("--timeout-floor", type=float, default=30.0)
    running.add_argument("--timeout-factor", type=float, default=4.0)
    running.add_argument("--strings", action="store_true")
    running.add_argument("--ids", help="a file of mutant ids, one per line: run only these")
    running.add_argument("--retest", action="append", help="rerun mutants recorded with this status")
    running.add_argument("--retest-killer",
                         help="rerun mutants an older runner recorded as killed by a test matching this pattern")
    running.add_argument("files", nargs="+")
    reporting = sub.add_parser("report", help="per-module totals and survivors, as Markdown")
    reporting.add_argument("--state", required=True)
    reporting.add_argument("--strings", action="store_true")
    reporting.add_argument("--survivors", action="store_true")
    reporting.add_argument("files", nargs="+")
    args = parser.parse_args()
    handler = {"map": cmd_map, "run": cmd_run, "report": cmd_report}[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
