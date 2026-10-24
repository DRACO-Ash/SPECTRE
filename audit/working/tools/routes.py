"""List FastAPI routes and their dependencies via AST. Usage: routes.py <repo>"""
import ast, sys, os, glob
os.chdir(sys.argv[1])
for f in sorted(glob.glob("spectre/web/**/*.py", recursive=True)):
    tree = ast.parse(open(f).read())
    prefix = ""
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "APIRouter":
            for k in n.keywords:
                if k.arg == "prefix": prefix = ast.literal_eval(k.value)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get","post","put","delete","patch","api_route","websocket"):
                    path = ast.literal_eval(d.args[0]) if d.args else "?"
                    deps = []
                    for a in n.args.args + n.args.kwonlyargs:
                        pass
                    lines=open(f).read().splitlines(); src="\n".join(lines[n.lineno-1:n.body[0].lineno-1])
                    auth = "require_login" in src or "require_admin" in src
                    opt = "optional_login" in src
                    adm = "require_admin" in src
                    csrf = "csrf" in src.lower()
                    print(f"{d.func.attr.upper():6} {prefix+path:45} {f}:{n.lineno} {n.name} auth={'admin' if adm else ('login' if auth else ('optional' if opt else 'NONE'))} csrf_param={csrf}")
