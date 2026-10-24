"""R5: cognitive_complexity double-count check (F-S10-11)."""
import sys, importlib.util
spec = importlib.util.spec_from_file_location("cc", sys.argv[1] + "/scripts/cognitive_complexity.py")
cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
srcs = {
 "a and g(b or c)": "def f(a,b,c):\n    if a and g(b or c):\n        pass\n",
 "a and g(h(b or c))": "def f(a,b,c):\n    if a and g(h(b or c)):\n        pass\n",
 "a and (b or c)": "def f(a,b,c):\n    if a and (b or c):\n        pass\n",
 "try/finally": "def f():\n    try:\n        pass\n    finally:\n        pass\n",
 "try/except": "def f():\n    try:\n        pass\n    except E:\n        pass\n",
}
for k, s in srcs.items():
    print(k, cc.measure_source(s, "x.py"))
