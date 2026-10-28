#!/usr/bin/env python3
"""Check changed code against every SonarQube rule the App Store gate has raised here.

The Code Quality gate scores new and changed lines only, and every failed
submission so far was one of a short list of rules that ruff does not
approximate. Each is encoded below as a check, with the version it was raised
in, so a rule that has cost a submission cannot cost another.

Two behaviours of the gate matter as much as the rules:

● Any edit to a line brings the issues already on that line into scope. 0.6.3
  rewrote ``title`` attributes on fields that had never had a label, and the
  missing labels were counted as new. So every check runs on every changed
  line or element, whatever the edit was for.
● Threshold rules (S1192, S107) fire on the occurrence that crosses the
  threshold. A literal used twice on the base and three times now is a new
  issue even if the edit only added one use.

The ledger of rules, their causes and their limits is docs/SONAR-RULES.md, and
a test holds this file and that table to the same list. When the gate raises a
rule that is not here, add a row there and a check here, with a test that
reproduces the gate's line, before fixing the code.

Standard library only. Reads git for the changed lines; no network.

Usage:  python3 scripts/sonar_rules.py [base]     (default: master)
        python3 scripts/sonar_rules.py --all [path ...]   every line, no base
Exit:   0 when nothing blocks, 1 when a finding lands on changed code.
"""

from __future__ import annotations

import ast
import bisect
import builtins
import importlib
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

#: The directories sonar-project.properties names as sonar.sources. Tests are
#: analysed under a reduced profile, and none of the rules below has been raised
#: on them, so they are not checked.
SOURCE_DIRS = ("spectre", "tle_clustering")
TEMPLATE_SUFFIXES = (".html", ".js")

#: rule id -> (version first raised, one-line description). The table in
#: docs/SONAR-RULES.md must list exactly these ids.
RULES: dict[str, tuple[str, str]] = {
    "python:S1192": ("0.6.0", "string literal used three or more times in a file"),
    "python:S1244": ("0.6.0", "float compared with == or !="),
    "python:S3358": ("0.6.0", "nested conditional expression"),
    "python:S107": ("0.6.0", "function with more than 13 parameters"),
    "python:S8410": ("0.6.0", "FastAPI dependency as a default rather than Annotated"),
    "python:S5713": ("0.6.0", "except tuple names a class and its subclass"),
    "python:S7504": ("0.6.0", "list() around an iterable that is being iterated"),
    "python:S6353": ("0.6.0", "regex character class with a shorthand equivalent"),
    "python:S7632": ("0.6.0", "noqa comment with text after its codes"),
    "javascript:S7773": ("0.6.1", "global parseFloat/parseInt/isNaN/isFinite"),
    "javascript:S7761": ("0.6.0", "data-* attribute through get/setAttribute, not dataset"),
    "Web:InputWithoutLabelCheck": ("0.6.3", "form field with no label tied to it"),
    "Web:S6819": ("0.6.0", "ARIA role with a native element equivalent"),
    "Web:JinjaCommentInTag": ("0.6.0", "Jinja comment inside a tag, read as attributes"),
}

# S1192: what the gate counts, inferred from what it has and has not raised
# (docs/SONAR-RULES.md). Every literal it flagged in 0.6.0 held a space, slash,
# hyphen or dot; identifier-like ones ("fields_side" three times, new in 0.6.4;
# "epoch" twelve times) never were. Literals under five characters never were.
_LITERAL_MIN_LEN = 5
_IDENTIFIER_LIKE = re.compile(r"^\w+$")
_LITERAL_THRESHOLD = 3
_MAX_PARAMS = 13

_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "api_route", "websocket"})
_FASTAPI_PARAMS = frozenset({"Depends", "Form", "Query", "Body", "Header", "Cookie", "File", "Path", "Security"})
_INJECTORS = frozenset({"Depends", "Security"})
_REGEX_FUNCS = frozenset({"compile", "match", "search", "fullmatch", "sub", "subn", "findall", "finditer", "split"})
_SHORTHAND_CLASSES = re.compile(r"\[\^?(?:0-9|a-zA-Z0-9_|A-Za-z0-9_|a-zA-Z_0-9|A-Za-z_0-9|_a-zA-Z0-9|0-9a-zA-Z_)\]")
_NOQA = re.compile(r"#\s*noqa\b(.*)$")
_NOQA_CODES = re.compile(r"^:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*")
#: Words in a Jinja comment inside a tag that Sonar's HTML parser has read as
#: attributes, raising S6819 and S6793 on text that is not markup.
_ATTRIBUTE_LIKE = re.compile(r"=|\brole\b|\baria-")

_JS_GLOBALS = re.compile(r"(?<![\w.$])(parseFloat|parseInt|isNaN|isFinite)\s*\(")
_JS_DATA_ATTR = re.compile(r"\.(?:get|set|remove|has)Attribute\(\s*(['\"])data-[\w-]*\1\s*[,)]")

#: Roles Sonar asks to replace with the element in the value.
_NATIVE_ROLES = {
    "button": "<button>", "checkbox": '<input type="checkbox">', "radio": '<input type="radio">',
    "heading": "<h1> to <h6>", "link": "<a href>", "list": "<ul> or <ol>", "listitem": "<li>",
    "navigation": "<nav>", "banner": "<header>", "contentinfo": "<footer>", "main": "<main>",
    "status": "<output>", "table": "<table>", "row": "<tr>", "cell": "<td>", "dialog": "<dialog>",
    "img": "<img> or <svg>",
}
_UNLABELLED_TYPES = frozenset({"hidden", "submit", "button", "reset", "image"})
_FIELD_TAGS = frozenset({"input", "select", "textarea"})
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    message: str
    blocking: bool = True

    def render(self) -> str:
        label = "FAIL" if self.blocking else "WARN"
        version = RULES[self.rule][0]
        return f"  {label}  {self.rule}  {self.path}:{self.line}  {self.message}  (raised in {version})"


# ── Python ────────────────────────────────────────────────────────────────────


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def literal_uses(source: str) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """(plain literals, f-string fragments) of at least the minimum length, with their lines."""
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    fragments = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    plain: dict[str, list[int]] = {}
    in_fstrings: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip or len(node.value) < _LITERAL_MIN_LEN or _IDENTIFIER_LIKE.match(node.value):
            continue
        target = in_fstrings if id(node) in fragments else plain
        target.setdefault(node.value, []).append(node.lineno)
    return plain, in_fstrings


def check_literals(path: str, source: str, base: str | None, changed: set[int]) -> list[Finding]:
    """S1192: a literal that crosses three uses with one of them on a changed line."""
    now, now_fragments = literal_uses(source)
    before, before_fragments = literal_uses(base) if base else ({}, {})
    findings = []
    for uses, prior, is_fragment in ((now, before, False), (now_fragments, before_fragments, True)):
        for literal, lines in uses.items():
            if len(lines) < _LITERAL_THRESHOLD or not changed.intersection(lines):
                continue
            was = len(prior.get(literal, []))
            if was >= _LITERAL_THRESHOLD and len(lines) <= was:
                continue
            new_issue = was < _LITERAL_THRESHOLD
            kind = "f-string fragment" if is_fragment else "literal"
            message = f"{kind} {literal!r} used {len(lines)} times (base {was}): make it a module constant"
            if not new_issue:
                message += "; already over the threshold on the base, so not new"
            findings.append(Finding("python:S1192", path, min(lines), message, new_issue and not is_fragment))
    return findings


def _is_float(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, float)


def _signature_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> range:
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return range(first, node.body[0].lineno)


def _route_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for deco in node.decorator_list:
        call = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(call, ast.Attribute) and call.attr in _ROUTE_METHODS:
            return True
    return False


def _callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """{local name: dotted origin} for every import in *tree*."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
    return names


def _resolve_class(node: ast.AST, imports: dict[str, str]) -> type | None:
    """The exception class *node* names, from builtins or a third-party import; None if unknown."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.insert(0, node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    if not parts and hasattr(builtins, node.id):
        found = getattr(builtins, node.id)
        return found if isinstance(found, type) else None
    origin = imports.get(node.id)
    if origin is None or origin.split(".")[0] in SOURCE_DIRS:
        return None  # local classes are not imported: that would run application code
    dotted = f"{origin}.{'.'.join(parts)}" if parts else origin
    module_name, _, attr = dotted.rpartition(".")
    try:
        found = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError, ValueError):
        return None
    return found if isinstance(found, type) else None


def _redundant_pair(handler: ast.ExceptHandler, imports: dict[str, str]) -> str | None:
    if not isinstance(handler.type, ast.Tuple):
        return None
    classes = [(ast.unparse(e), _resolve_class(e, imports)) for e in handler.type.elts]
    for name, cls in classes:
        for other_name, other in classes:
            if cls and other and cls is not other and issubclass(cls, other):
                return f"{name} is a subclass of {other_name}: drop {name}"
    return None


def _list_around_iterable(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "list"
        and len(node.args) == 1 and not node.keywords
    )


def _regex_findings(node: ast.Call) -> Iterator[str]:
    if not (isinstance(node.func, ast.Attribute) and node.func.attr in _REGEX_FUNCS):
        return
    if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "re"):
        return
    for arg in node.args[:1]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            match = _SHORTHAND_CLASSES.search(arg.value)
            if match:
                yield match.group(0)


def _node_findings(path: str, tree: ast.AST, changed: set[int]) -> Iterator[Finding]:
    imports = _imported_names(tree)
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare) and line in changed:
            sides = [node.left, *node.comparators]
            if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops) and any(map(_is_float, sides)):
                yield Finding("python:S1244", path, line, "exact float comparison: compare with a named tolerance")
        elif isinstance(node, ast.IfExp) and line in changed:
            if any(isinstance(n, ast.IfExp) for part in (node.body, node.orelse, node.test) for n in ast.walk(part)):
                yield Finding("python:S3358", path, line, "nested conditional expression: use statements")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _function_findings(path, node, changed)
        elif isinstance(node, ast.ExceptHandler) and line in changed:
            pair = _redundant_pair(node, imports)
            if pair:
                yield Finding("python:S5713", path, line, pair)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            target = node.iter
            if _list_around_iterable(target) and getattr(target, "lineno", 0) in changed:
                yield Finding(
                    "python:S7504", path, target.lineno,  # type: ignore[attr-defined]
                    "list() around the iterable: iterate it directly, or copy with .copy() or [*x] if it mutates",
                )
        elif isinstance(node, ast.Call) and line in changed:
            for found in _regex_findings(node):
                yield Finding("python:S6353", path, line, f"{found} in a regex: use \\d or \\w (with re.ASCII)")


def _function_findings(
    path: str, node: ast.FunctionDef | ast.AsyncFunctionDef, changed: set[int],
) -> Iterator[Finding]:
    if not changed.intersection(_signature_lines(node)):
        return
    args = node.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    named = [a for a in params if a.arg not in {"self", "cls"}]
    count = len(named) + bool(args.vararg) + bool(args.kwarg)
    if count > _MAX_PARAMS:
        yield Finding("python:S107", path, node.lineno, f"{node.name} takes {count} parameters (limit {_MAX_PARAMS}): bind a model")
    # Depends and Security inject wherever they appear, so any function using
    # them as a default counts; the request parameters only mean anything on a
    # route.
    kinds = _FASTAPI_PARAMS if _route_function(node) else _INJECTORS
    defaults = [*([None] * (len(args.posonlyargs) + len(args.args) - len(args.defaults))), *args.defaults, *args.kw_defaults]
    for arg, default in zip([*args.posonlyargs, *args.args, *args.kwonlyargs], defaults, strict=False):
        if default is not None and _callee_name(default) in kinds and arg.lineno in changed:
            yield Finding(
                "python:S8410", path, arg.lineno,
                f"{arg.arg} = {_callee_name(default)}(...): use Annotated[type, {_callee_name(default)}(...)]",
            )


def noqa_has_text(comment: str) -> bool:
    """Whether a ``# noqa`` comment carries anything after its codes."""
    match = _NOQA.search(comment)
    return bool(match and _NOQA_CODES.sub("", match.group(1)).strip())


def _comment_findings(path: str, source: str, changed: set[int]) -> Iterator[Finding]:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return
    for tok in tokens:
        if tok.type == tokenize.COMMENT and tok.start[0] in changed and noqa_has_text(tok.string):
            yield Finding("python:S7632", path, tok.start[0], "text after the noqa codes: move the rationale to the line above")


def check_python(path: str, source: str, base: str | None, changed: set[int]) -> list[Finding]:
    """Every Python rule on *source*, scoped to *changed* lines."""
    tree = ast.parse(source)
    return [
        *check_literals(path, source, base, changed),
        *_node_findings(path, tree, changed),
        *_comment_findings(path, source, changed),
    ]


# ── Templates and JavaScript ──────────────────────────────────────────────────


@dataclass
class Tag:
    name: str
    start: int
    end: int
    text: str
    jinja_comments: list[str] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)


def _skip_jinja(text: str, i: int) -> int:
    """The index just past the Jinja block opening at *i*."""
    closer = {"{{": "}}", "{%": "%}", "{#": "#}"}[text[i:i + 2]]
    end = text.find(closer, i + 2)
    return len(text) if end < 0 else end + 2


def _script_spans(text: str) -> list[tuple[int, int]]:
    """Where <script> bodies are: Sonar does not parse their contents as HTML."""
    return [(m.start(), m.end()) for m in re.finditer(r"<script\b.*?</script>", text, re.S | re.I)]


def tags(text: str) -> Iterator[Tag]:
    """Every opening tag in *text* outside <script> bodies, reading past Jinja blocks and quoted values."""
    scripts = _script_spans(text)
    i = 0
    while True:
        i = text.find("<", i)
        if i < 0 or i + 1 >= len(text):
            return
        inside = next((end for start, end in scripts if start < i < end - len("</script>")), None)
        if inside is not None:
            i = inside - len("</script>")
            continue
        if not text[i + 1].isalpha():
            i += 1
            continue
        j, quote, comments = i + 1, "", []
        while j < len(text):
            ch = text[j]
            if quote:
                quote = "" if ch == quote else quote
            elif text[j:j + 2] in ("{{", "{%", "{#"):
                after = _skip_jinja(text, j)
                if text[j:j + 2] == "{#":
                    comments.append(text[j:after])
                j = after
                continue
            elif ch in "\"'":
                quote = ch
            elif ch == ">":
                break
            j += 1
        body = text[i:j + 1]
        name = re.match(r"<([a-zA-Z][\w-]*)", body)
        attrs = {m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3) for m in _ATTR.finditer(body)}
        yield Tag(name.group(1).lower() if name else "", i, j, body, comments, attrs)
        i = j + 1


def _line_of(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def _inside_label(text: str, offset: int) -> bool:
    return text.rfind("<label", 0, offset) > text.rfind("</label>", 0, offset)


def _tag_findings(path: str, text: str, changed: set[int]) -> Iterator[Finding]:
    starts = [0, *(m.end() for m in re.finditer("\n", text))]
    labelled = set(re.findall(r"""<label\b[^>]*\bfor\s*=\s*["']([^"']+)["']""", text))
    for tag in tags(text):
        first, last = _line_of(starts, tag.start), _line_of(starts, tag.end)
        if not changed.intersection(range(first, last + 1)):
            continue
        if tag.jinja_comments:
            parsed = any(_ATTRIBUTE_LIKE.search(c) for c in tag.jinja_comments)
            yield Finding(
                "Web:JinjaCommentInTag", path, first,
                f"{{# #}} inside <{tag.name}>: move the comment above the tag"
                + ("; its words read as attributes" if parsed else "; harmless until it mentions an attribute"),
                parsed,
            )
        role = tag.attrs.get("role", "").strip()
        if role in _NATIVE_ROLES and not (role == "img" and tag.name in {"svg", "img"}):
            yield Finding("Web:S6819", path, first, f'role="{role}" on <{tag.name}>: use {_NATIVE_ROLES[role]}')
        if tag.name in _FIELD_TAGS and tag.attrs.get("type", "").lower() not in _UNLABELLED_TYPES:
            field_id = tag.attrs.get("id")
            if not (_inside_label(text, tag.start) or (field_id and field_id in labelled)):
                yield Finding(
                    "Web:InputWithoutLabelCheck", path, first,
                    f"<{tag.name}> has no label: give it an id and a <label for>, or wrap it in <label>",
                )


def check_template(path: str, text: str, changed: set[int]) -> list[Finding]:
    """Every template and JavaScript rule on *text*, scoped to *changed* lines."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if number not in changed:
            continue
        for match in _JS_GLOBALS.finditer(line):
            findings.append(Finding("javascript:S7773", path, number, f"{match.group(1)}(): use Number.{match.group(1)}()"))
        if _JS_DATA_ATTR.search(line):
            findings.append(Finding("javascript:S7761", path, number, "data-* attribute: use element.dataset"))
    if path.endswith(".html"):
        findings.extend(_tag_findings(path, text, changed))
    return findings


# ── Scope ─────────────────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout  # noqa: S603, S607


#: Vendored, minified third-party libraries. They are never edited here (their
#: versions are pinned in spectre/web/static/vendored.json), SonarJS skips
#: minified files (INFERENCE, docs/SONAR-RULES.md), and they enter the new-code
#: window only when replaced whole by an upgrade.
_VENDORED = ".min.js"


def _in_scope(path: str) -> bool:
    return (
        path.startswith(tuple(f"{d}/" for d in SOURCE_DIRS))
        and path.endswith((".py", *TEMPLATE_SUFFIXES))
        and not path.endswith(_VENDORED)
    )


def resolve_base(base: str) -> str:
    """*base*, or its remote-tracking branch when the local one is behind it.

    A stale local master makes every commit released since it was last pulled
    read as this branch's work: on 28 October 2026 that turned 0 findings into
    14. CI fetches the base fresh; a developer's checkout often has not.
    """
    remote = f"origin/{base}"
    try:
        _git("rev-parse", "--verify", "--quiet", remote)
        _git("merge-base", "--is-ancestor", base, remote)
    except subprocess.CalledProcessError:
        return base
    return remote


def changed_lines(base: str) -> tuple[str, dict[str, set[int]]]:
    """(merge-base commit, {path: lines added or modified}) for the working tree against *base*.

    Against the merge base and the working tree, untracked files whole, for the
    reasons scripts/sonar_scope.py records.
    """
    base = resolve_base(base)
    try:
        anchor = _git("merge-base", base, "HEAD").strip() or base
    except subprocess.CalledProcessError:
        anchor = base
    changed: dict[str, set[int]] = {}
    path = ""
    for line in _git("diff", "-U0", anchor).splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif path and (hunk := re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)):
            start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
            changed.setdefault(path, set()).update(range(start, start + count))
    for entry in _git("ls-files", "--others", "--exclude-standard").splitlines():
        if Path(entry).is_file():
            changed[entry] = set(range(1, len(Path(entry).read_text(encoding="utf-8").splitlines()) + 2))
    return anchor, {p: lines for p, lines in changed.items() if _in_scope(p) and lines}


def _base_source(anchor: str, path: str) -> str | None:
    try:
        return _git("show", f"{anchor}:{path}")
    except subprocess.CalledProcessError:
        return None


def check_file(path: str, changed: set[int], base_source: str | None) -> list[Finding]:
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".py"):
        return check_python(path, text, base_source, changed)
    return check_template(path, text, changed)


def _all_lines(paths: Iterable[str]) -> dict[str, set[int]]:
    files = [p for root in paths for p in ([root] if Path(root).is_file() else map(str, Path(root).rglob("*")))]
    return {f: set(range(1, len(Path(f).read_text(encoding="utf-8").splitlines()) + 2))
            for f in files if _in_scope(f) and Path(f).is_file()}


def main(argv: list[str]) -> int:
    if argv[:1] == ["--all"]:
        anchor, scope = None, _all_lines(argv[1:] or SOURCE_DIRS)
    else:
        anchor, scope = changed_lines(argv[0] if argv else "master")
    findings = [
        f for path, lines in sorted(scope.items()) if Path(path).is_file()
        for f in check_file(path, lines, _base_source(anchor, path) if anchor else None)
    ]
    for finding in sorted(findings, key=lambda f: (not f.blocking, f.path, f.line)):
        print(finding.render())
    blocking = sum(f.blocking for f in findings)
    print(f"  {len(scope)} file(s) checked against {len(RULES)} rules: "
          f"{blocking} blocking, {len(findings) - blocking} advisory.")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
