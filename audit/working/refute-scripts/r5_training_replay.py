"""R5 refutation: training replay, duplicate objectives, level gating, scenario mismatch, bad JSON, session leak."""
import asyncio, os, re, sys, json, math
TREE = "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree"
sys.path.insert(0, TREE)
os.chdir(TREE)
os.environ["SECRET_KEY"] = "ci-only-ephemeral-signing-key-not-a-secret"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SPECTRE_ADMIN_USER"] = "testadmin"
os.environ["SPECTRE_ADMIN_PASS"] = "testpass123"
os.environ["SPECTRE_COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient
from spectre.web.app import app
from spectre.web.database import init_db
from spectre.web.csrf import make_csrf_token

asyncio.run(init_db())

def progress(c, ck):
    # read from DB via dashboard text
    r = c.get("/training/dashboard", cookies={"spectre_session": ck})
    return r.text

async def get_prog():
    from spectre.web.database import get_db
    from spectre.training.models import TrainingProgress
    from sqlalchemy import select
    agen = get_db()
    db = await agen.__anext__()
    p = (await db.execute(select(TrainingProgress))).scalars().all()
    out = [(x.username, x.total_points, x.current_level, x.scenarios_passed, x.challenges_passed) for x in p]
    await agen.aclose()
    return out

with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/login", data={"username": "testadmin", "password": "testpass123"}, follow_redirects=False)
    ck = r.cookies["spectre_session"]
    H = {"X-CSRF-Token": make_csrf_token(ck)}
    C = {"spectre_session": ck}
    c.get("/training", cookies=C)

    def start(sid, mode="start"):
        r = c.post(f"/training/scenario/{sid}/{mode}", cookies=C, headers=H)
        m = re.search(r'name="result_id"\s+value="(\d+)"', r.text) or re.search(r'result_id[^0-9]{0,40}(\d+)', r.text)
        return r.status_code, (int(m.group(1)) if m else None)

    def submit(sid, rid, objs, answers=None, t="1.0"):
        data = {"result_id": str(rid), "objectives_completed": objs if isinstance(objs, str) else json.dumps(objs), "time_taken_minutes": t}
        for k, v in (answers or {}).items():
            data[f"answer_{k}"] = v
        return c.post(f"/training/scenario/{sid}/submit", data=data, cookies=C, headers=H)

    # 01 replay
    sc, rid = start("cadet_01_geo_stationkeeping")
    print("start cadet_01", sc, rid)
    ans = {"obj_read_elements": "45.0", "obj_confirm_dv": "2.0"}
    objs = ["obj_load", "obj_read_elements", "obj_confirm_dv"]
    for i in range(3):
        r = submit("cadet_01_geo_stationkeeping", rid, objs, ans)
        print("submit#", i + 1, r.status_code, asyncio.run(get_prog()))

    # 02 duplicate objectives on planner_05 (self-cert objectives?) -> use cadet_01 obj_load duplicated
    sc, rid2 = start("cadet_01_geo_stationkeeping")
    r = submit("cadet_01_geo_stationkeeping", rid2, ["obj_load"] * 6)
    m = re.search(r"(\d+)\s*/\s*\d+", r.text)
    print("dup obj_load x6 on cadet_01:", r.status_code, "passed" if "PASS" in r.text.upper() else "?", asyncio.run(get_prog()))

    # 03 level gating: start Level 5 challenge at whatever level
    sc, rid3 = start("planner_challenge_theatre_defence")
    print("start L5 challenge:", sc, rid3, asyncio.run(get_prog()))
    # detail view gate
    print("detail L5:", c.get("/training/scenario/planner_challenge_theatre_defence", cookies=C).status_code)
    # mismatched scenario: score rid3 (theatre_defence row) against cadet_01 objectives
    r = submit("cadet_01_geo_stationkeeping", rid3, objs, ans)
    print("mismatch submit:", r.status_code, asyncio.run(get_prog()))

    # 19 bad JSON shapes
    sc, rid4 = start("cadet_02_leo_debris_conjunction")
    for bad in ["5", "[{}]", '{"a":1}', "null"]:
        r = submit("cadet_02_leo_debris_conjunction", rid4, bad)
        print("objectives_completed=", bad, "->", r.status_code)
    for t in ["-5", "nan", "inf"]:
        sc, rid5 = start("cadet_02_leo_debris_conjunction")
        r = submit("cadet_02_leo_debris_conjunction", rid5, [], t=t)
        print("time_taken=", t, "->", r.status_code)

    # 06 session state leak
    from spectre.web.planning_state import get_session_state
    st = get_session_state("testadmin")
    print("blue after start:", [b.name for b in st.blue_assets])
    print("red after start:", [x.name for x in st.red_tracks])
    c.post("/training/leave", data={"session_id": "0"}, cookies=C, headers=H, follow_redirects=False)
    home = c.get("/", cookies=C).text
    print("BLUE-01 on / after leave:", "BLUE-01" in home)

    # 04 free-play pass points: fresh user? use points delta already printed
