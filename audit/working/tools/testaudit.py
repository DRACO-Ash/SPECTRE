"""Classify test files and flag weak tests by AST. Usage: testaudit.py <repo> <out.md> <flags.md>"""
import ast, sys, os, glob, re, collections
repo, out, flags_out = sys.argv[1:4]; os.chdir(repo)
NAME_RE = re.compile(r"^test_should_\w+_when_\w+$")
def kinds(path, src, tree):
    k = set()
    if path.startswith("tests/integration/") or "TestClient" in src or "AsyncClient(" in src: k.add("integration")
    if "hypothesis" in src: k.add("property")
    if re.search(r"contract|_gates|committable|quality_gate|deployment", path): k.add("contract")
    if re.search(r"(?i)regression|before the fix|the defect|was \d|published answer", src): k.add("regression")
    if "smoke" in src.lower(): k.add("smoke")
    if not k or k <= {"regression", "smoke"}: k.add("unit")
    return sorted(k)
def is_assertive(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Assert): return True
        if isinstance(n, ast.With):
            for it in n.items:
                c = it.context_expr
                if isinstance(c, ast.Call) and getattr(c.func, "attr", "") in ("raises", "warns", "deprecated_call"): return True
        if isinstance(n, ast.Call):
            nm = getattr(n.func, "attr", getattr(n.func, "id", ""))
            if nm.lstrip("_").startswith(("assert", "expect", "check", "verify", "require")) or nm in ("fail", "_assert", "check"): return True
    return False
def trivial_only(node):
    asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
    if not asserts: return False
    def triv(t):
        s = ast.unparse(t.test)
        return bool(re.fullmatch(r"(.+ is not None|isinstance\(.+\)|.+|True|len\(.+\) >= 0|.+ is None)", s)) and (" is not None" in s or s.startswith("isinstance(") or s in ("True",))
    return all(triv(a) for a in asserts)
def mock_only(node):
    asserts = [ast.unparse(n.test) for n in ast.walk(node) if isinstance(n, ast.Assert)]
    calls = [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.Call) and getattr(n.func, "attr", "").startswith("assert_called")]
    return bool(calls) and not asserts
rows = []; flags = []; tally = collections.Counter(); naming = collections.Counter(); per_kind = collections.Counter()
for f in sorted(glob.glob("tests/**/test_*.py", recursive=True)):
    src = open(f).read(); tree = ast.parse(src)
    tests = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")]
    k = kinds(f, src, tree)
    for kk in k: per_kind[kk] += 1
    nf = 0
    for t in tests:
        naming["conforming" if NAME_RE.match(t.name) else "nonconforming"] += 1
        if not is_assertive(t): flags.append((f, t.lineno, t.name, "NO-ASSERTION")); nf += 1
        elif trivial_only(t): flags.append((f, t.lineno, t.name, "TRIVIAL-ASSERTION-ONLY")); nf += 1
        elif mock_only(t): flags.append((f, t.lineno, t.name, "MOCK-ONLY")); nf += 1
    # duplicate bodies
    bodies = collections.defaultdict(list)
    for t in tests:
        body = ast.dump(ast.Module(body=t.body, type_ignores=[]))
        bodies[body].append(t)
    for b, ts in bodies.items():
        if len(ts) > 1 and not any(d for t in ts for d in t.decorator_list):
            for t in ts[1:]: flags.append((f, t.lineno, t.name, f"DUPLICATE-BODY of {ts[0].name}")); nf += 1
    rows.append((f, ", ".join(k), len(tests), nf))
with open(out, "w") as fh:
    fh.write("| Test file | Classification | Test functions | Flagged |\n|---|---|---|---|\n")
    for f, k, n, nf in rows: fh.write(f"| `{f}` | {k} | {n} | {nf} |\n")
with open(flags_out, "w") as fh:
    fh.write("| Path:line | Test | Flag |\n|---|---|---|\n")
    for f, l, n, why in flags: fh.write(f"| `{f}:{l}` | `{n}` | {why} |\n")
print("files", len(rows), "functions", sum(r[2] for r in rows)); print("kinds", dict(per_kind)); print("naming", dict(naming))
print("flags", collections.Counter(x[3].split(" ")[0] for x in flags))
