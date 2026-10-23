import sys, pathlib
from playwright.sync_api import sync_playwright
htmx = pathlib.Path("/home/user/SPECTRE/spectre/web/static/htmx.min.js").read_text()
frag = """<div><input type="text" name="manual_name" id="ts-manual-name" value="">
<select name="manual_confidence"><option value="MEDIUM" selected>MEDIUM</option></select>
<textarea name="manual_tle" id="ts-manual-tle"></textarea>
<button type="button" id="b" hx-post="/plan/threat/add-manual-tle" hx-target="#manual-tle-list" hx-swap="outerHTML"
 hx-include="[name='manual_name'],[name='manual_tle'],[name='manual_confidence']"
 onclick="document.getElementById('ts-manual-name').value=''; document.getElementById('ts-manual-tle').value='';">Add TLE</button>
<div id="manual-tle-list"></div></div>"""
page_html = f"<html><head><script>{htmx}</script></head><body><div id='host' hx-get='/frag' hx-trigger='load' hx-swap='innerHTML'></div></body></html>"
bodies = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
    pg = b.new_page()
    def handler(route):
        u = route.request.url
        if u.endswith("/frag"): return route.fulfill(body=frag, content_type="text/html")
        if "add-manual-tle" in u:
            bodies.append(route.request.post_data); return route.fulfill(body="<div id='manual-tle-list'>ok</div>", content_type="text/html")
        return route.fulfill(body=page_html, content_type="text/html")
    pg.route("**/*", handler)
    pg.goto("http://example.test/")
    pg.wait_for_selector("#b")
    pg.fill("#ts-manual-name", "TARGET-X"); pg.fill("#ts-manual-tle", "1 abc\n2 def")
    pg.click("#b"); pg.wait_for_timeout(500)
    print("htmx version:", pg.evaluate("htmx.version"))
    print("posted:", bodies)
    b.close()
