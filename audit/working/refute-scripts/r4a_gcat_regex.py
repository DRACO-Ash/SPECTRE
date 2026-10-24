import sys, os, time
sys.path.insert(0, sys.argv[1]); os.environ.setdefault("SECRET_KEY","ci-only-ephemeral-signing-key-not-a-secret")
import pandas as pd
from spectre.web.routes import gcat
df = pd.DataFrame({"a":["x"*25+"!"]*200, "b":["foo"]*200})
gcat._CACHE["currentcat"]={"df":df,"columns":list(df.columns),"rows":200,"cols":2}
for q in ["(", "(a+)+$", "x.*"]:
    t=time.perf_counter()
    try:
        r=gcat._page_data("currentcat", q=q); print(repr(q), "ok rows", r["filtered_rows"] if "filtered_rows" in r else "?", round(time.perf_counter()-t,3))
    except Exception as e: print(repr(q), type(e).__name__, e, round(time.perf_counter()-t,3))
df2 = pd.DataFrame({"a":["a"*24+"!"]*3})
gcat._CACHE["currentcat"]={"df":df2,"columns":["a"],"rows":3,"cols":1}
t=time.perf_counter()
gcat._page_data("currentcat", q="(a+)+$"); print("redos 3 rows len25:", round(time.perf_counter()-t,2),"s")
