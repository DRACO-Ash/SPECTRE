import pathlib, sys, os
os.environ["SECRET_KEY"]="ci-only-ephemeral-signing-key-not-a-secret"
sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright
env = Environment(loader=FileSystemLoader("/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree/spectre/web/templates"), autoescape=select_autoescape(["html"]))
htmx = pathlib.Path("/home/user/SPECTRE/spectre/web/static/htmx.min.js").read_text()
names = ['Plain', 'Has "quote"', 'Back\\slash']
frag = env.get_template("partials/sweep_manual_tles.html").render(manual_tles=[{"name":n,"tle":"x","confidence":"LOW"} for n in names], error=None)
page_html = f"<html><head><script>{htmx}</script></head><body>{frag}</body></html>"
bodies=[]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=sys.argv[1]); pg=b.new_page()
    def h(route):
        if "remove-manual-tle" in route.request.url:
            bodies.append(route.request.post_data); return route.fulfill(body="", content_type="text/html")
        return route.fulfill(body=page_html, content_type="text/html")
    pg.route("**/*", h); pg.goto("http://example.test/")
    btns = pg.query_selector_all("[hx-post*='remove-manual-tle']")
    print("buttons", len(btns))
    for i in range(len(btns)):
        pg.goto("http://example.test/"); pg.query_selector_all("[hx-post*='remove-manual-tle']")[i].click(); pg.wait_for_timeout(300)
    print(bodies); b.close()
