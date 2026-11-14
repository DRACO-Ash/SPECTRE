"""Puts the "how to use me" feature into a board page and keeps its text in step with assets/how-to-use.json.

The page carries the guide as a JSON literal between two markers. apply() adds the feature to a page that does not
have it yet; embed() refreshes the literal from the source file. Both are exact: an anchor that is missing or matches
more than once is an error, never a silent skip.
"""
import json
import re

from .guide import load_guide

BEGIN, END = "/*HOWTO:BEGIN*/", "/*HOWTO:END*/"

CSS = """dialog.how{width:min(680px,calc(100vw - 32px));max-height:min(86vh,820px)}
dialog.how form{display:grid;gap:12px;padding:16px 18px;max-height:min(86vh,820px);overflow:auto}
dialog.how .intro{margin:0;color:var(--ink)}
dialog.how ul.who{margin:0;padding:0;list-style:none;display:grid;gap:4px;font-size:13px;color:var(--ink-2)}
dialog.how ul.who li{padding-left:16px;position:relative}
dialog.how ul.who li::before{content:"\\25cf";position:absolute;left:0;color:var(--blue)}
dialog.how details.job{border:1px solid var(--line);border-radius:9px;background:var(--panel-2)}
dialog.how details.job>summary{cursor:pointer;padding:10px 12px;font-weight:600;color:var(--navy);list-style:none}
dialog.how details.job>summary::-webkit-details-marker{display:none}
dialog.how details.job>summary::after{content:"\\203A";float:right;transition:transform .15s}
dialog.how details.job[open]>summary::after{transform:rotate(90deg)}
dialog.how details.job>summary:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-radius:9px}
dialog.how details.job ol{margin:0;padding:0 14px 12px 32px;display:grid;gap:7px;font-size:13.5px;line-height:1.45}
@media (prefers-reduced-motion:reduce){dialog.how details.job>summary::after{transition:none}}
"""

BUTTON = '<button class="btn ghost" id="howBtn" type="button" aria-haspopup="dialog">How to use me</button>\n    '
DIALOG = """<dialog class="dec how" id="howDlg" aria-labelledby="howH">
  <form id="howForm" method="dialog">
    <h3 id="howH"></h3>
    <p class="intro" id="howIntro"></p>
    <ul class="who" id="howWho"></ul>
    <div id="howJobs"></div>
    <div class="row"><button class="btn" type="submit" id="howClose">Close</button></div>
  </form>
</dialog>
"""
JS = """  // HOW TO USE ME (owner, 2026-10-02). The text is assets/how-to-use.json, embedded between the markers by
  // brain/page_patch.py, so the page and the portable pack read one source.
  const HOW = %s%s%s;
  function renderHow(){
    if (!$("howDlg")) return;
    const g = fillGuide(HOW, S);
    $("howH").textContent = g.title; $("howIntro").textContent = g.intro;
    $("howWho").innerHTML = (g.who || []).map(w => `<li>${esc(w)}</li>`).join("");
    $("howJobs").innerHTML = g.jobs.map(j => `<details class="job" data-job="${esc(j.id)}"><summary>${esc(j.title)}</summary><ol>${j.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol></details>`).join("");
    $("howJobs").style.display = "grid"; $("howJobs").style.gap = "8px";
  }
  (() => {
    const btn = $("howBtn"), dlg = $("howDlg");
    if (!btn || !dlg) return;
    renderHow();
    btn.addEventListener("click", () => { if (!dlg.open) dlg.showModal(); });
    dlg.addEventListener("close", () => btn.focus());
  })();
"""


def _once(text, anchor):
    n = text.count(anchor)
    if n != 1:
        raise ValueError(f"anchor found {n} times, expected once: {anchor[:60]!r}")


def literal(guide=None):
    return json.dumps((guide or load_guide())["board"], ensure_ascii=False, indent=1)


def apply(html, guide=None):
    """Add the feature to a page that does not have it. Refuses a page that already has it."""
    if BEGIN in html:
        raise ValueError("the page already has the how to use me feature; use embed()")
    if "/*SETTINGS:BEGIN*/" not in html:     # the guide's tokens are filled from the page's settings (VH-584)
        raise ValueError("the page has no settings block, so the guide's tokens could not be filled; add the settings first")
    a_css = "dialog.dec::backdrop{background:rgba(5,12,24,.55)}\n"
    a_btn = '<button class="btn" id="decQBtn" type="button" hidden>'
    a_dlg = '<div class="tip" id="tip" hidden></div>'
    a_js = '  $("decQBtn").addEventListener("click", () => {'
    for a in (a_css, a_btn, a_dlg, a_js):
        _once(html, a)
    html = html.replace(a_css, a_css + CSS, 1)
    html = html.replace(a_btn, BUTTON + a_btn, 1)
    html = html.replace(a_dlg, DIALOG + a_dlg, 1)
    html = html.replace(a_js, JS % (BEGIN, literal(guide), END) + a_js, 1)
    return html


def embed(html, guide=None):
    """Refresh the guide literal in a page that has the feature."""
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if len(pat.findall(html)) != 1:
        raise ValueError("the page does not carry exactly one guide literal")
    return pat.sub(lambda m: BEGIN + literal(guide) + END, html, count=1)


def embedded(html):
    """The guide literal a page carries, parsed; None when the page has none."""
    m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), html, re.S)
    return json.loads(m.group(1)) if m else None
