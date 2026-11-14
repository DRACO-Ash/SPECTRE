"""Puts the Approvals panel into a board page.

The owner's instruction, 2026-10-05: approvals, screenshot approvals included, should be available in Backlog Brain,
easy to understand and answered in a single click. A decision on the board is an item with state "input" and a
`decision` object. A screenshot approval is the same item with `decision.images`, a list of {id, alt, caption}, where
`id` is the 32 character id of an asset uploaded to the board. The panel reads those items; it adds no collection and
no new field a thread has to learn beyond `images` and `kind`.

apply() adds the feature to a page that does not have it. Every anchor must match exactly once, or nothing is written.
"""
import re

BEGIN, END = "/*APPROVALS:BEGIN*/", "/*APPROVALS:END*/"

CSS = """
/* APPROVALS (owner, 2026-10-05): a decision or a screenshot approval, answered with one press. */
.appr{border-left:5px solid var(--blue)}
.appr .ph{padding-bottom:2px}
.appr-n{display:inline-block;min-width:22px;padding:0 7px;margin-left:8px;border-radius:999px;background:var(--blue-bg);color:var(--blue);font-size:12px;line-height:20px;text-align:center;vertical-align:1px}
.appr-list{display:grid;gap:12px;padding:8px 16px 16px}
.appr-c{display:grid;grid-template-columns:minmax(0,330px) minmax(0,1fr);gap:16px;padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--panel-2)}
.appr-c.noimg{grid-template-columns:minmax(0,1fr)}
@media (max-width:760px){.appr-c{grid-template-columns:minmax(0,1fr)}}
.appr-c.shot{border-color:var(--adv)}
.appr-meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--ink-2)}
.appr-meta .ref{font-weight:700;color:var(--blue)}
.appr-kind{padding:2px 9px;border-radius:999px;font-weight:650;background:var(--blue-bg);color:var(--blue)}
.shot .appr-kind{background:var(--adv-bg);color:var(--adv)}
.appr-q{margin:6px 0 4px;font-size:16px;line-height:1.3;font-weight:650;color:var(--navy)}
.appr-t{margin:0;font-size:13px;color:var(--ink-2)}
.appr-ctx{margin:6px 0 0;font-size:13px;color:var(--ink)}
.appr-shots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;align-content:start}
.appr-shot{appearance:none;display:block;width:100%;padding:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel);cursor:zoom-in;text-align:left;font:inherit;color:inherit}
.appr-shot:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.appr-shot img{display:block;width:100%;height:auto;height:92px;object-fit:cover;object-position:top center;background:var(--idle-bg)}
.appr-shot span{display:block;padding:5px 8px;font-size:11.5px;color:var(--ink-2)}
.appr-more{grid-column:1/-1;font-size:12px;color:var(--ink-3)}
.appr-rec{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:700;color:#fff}
.appr-acts{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin-top:12px}
.appr-b{appearance:none;display:grid;gap:2px;text-align:left;padding:10px 12px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);font:inherit;cursor:pointer;min-height:48px}
.appr-b b{font-size:14px;font-weight:650}
.appr-b small{font-size:12px;color:var(--ink-2)}
.appr-b:hover{border-color:var(--blue)}
.appr-b:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.appr-b.rec{background:#17753f;border-color:#17753f;color:#fff}
.appr-b.rec small{color:#fff}
.appr-b[disabled]{opacity:.55;cursor:default}
.appr-note{display:grid;gap:6px;margin-top:10px}
.appr-note textarea{font:inherit;padding:7px 10px;border-radius:7px;border:1px solid var(--line);background:var(--panel);color:var(--ink);width:100%;min-height:64px;resize:vertical}
.appr-note .row{display:flex;gap:8px;flex-wrap:wrap}
.appr-undo{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:6px 16px 0;padding:9px 12px;border-radius:9px;background:var(--good-bg);color:var(--good);font-weight:600}
.appr-undo .btn{background:transparent;color:var(--good);border-color:var(--good)}
.appr-hint{font-size:12px;color:var(--ink-2)}
dialog.lb{border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);box-shadow:var(--shadow);padding:0;width:min(1100px,calc(100vw - 24px));max-height:calc(100vh - 24px)}
dialog.lb::backdrop{background:rgba(5,12,24,.7)}
dialog.lb .lbbody{display:grid;gap:8px;padding:12px 14px;max-height:calc(100vh - 28px);overflow:auto}
dialog.lb img{display:block;max-width:100%;height:auto;margin:0 auto;border-radius:6px}
dialog.lb .lbbar{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}
dialog.lb .lbcap{font-size:13px;color:var(--ink-2)}
@media (prefers-reduced-motion:reduce){.appr-b{transition:none}}
"""

PANEL = """  <section class="panel appr" id="apprPanel" aria-labelledby="apprH" hidden>
    <div class="ph"><h2 id="apprH">Waiting for your approval<span class="appr-n" id="apprN">0</span></h2><span class="appr-hint">One press answers it. You have 10 seconds to undo.</span></div>
    <div class="appr-undo" id="apprUndo" role="status" hidden><span id="apprUndoTxt"></span><button class="btn sm" type="button" id="apprUndoBtn">Undo</button></div>
    <div class="appr-list" id="apprList"></div>
  </section>

"""

DIALOG = """<dialog class="lb" id="lbDlg" aria-labelledby="lbCap">
  <div class="lbbody">
    <div class="lbbar"><span class="lbcap" id="lbCap"></span><span class="rowtools"><button class="btn ghost sm" type="button" id="lbPrev">Previous</button><button class="btn ghost sm" type="button" id="lbNext">Next</button><button class="btn sm" type="button" id="lbClose">Close</button></span></div>
    <img id="lbImg" alt="">
  </div>
</dialog>
"""

JS = r"""  %s
  // APPROVALS (owner, 2026-10-05): "Approvals should also be available via backlog brain, to include any screenshot
  // approvals. These should be made easy to comprehend and action in a single click." A card is an item with a
  // decision. A screenshot approval carries decision.images, a list of {id, alt, caption} naming assets uploaded to
  // this board. One press on an option writes the answer at once; the notice to Claude waits 10 seconds so an
  // accidental press can be undone, and Undo puts the item back exactly as it was.
  const APPR_UNDO_MS = 10000, apprDraft = new Map();
  let apprPend = null, lbSet = [], lbAt = 0;
  const imgOk = im => /^[0-9a-f]{32}$/.test(String(im?.id || ""));
  const apprImgs = i => (Array.isArray(i.decision?.images) ? i.decision.images : []).filter(imgOk).slice(0, 8);
  const apprIsShot = i => apprImgs(i).length > 0 || i.decision?.kind === "screenshot";
  const apprFlat = (t, n) => String(t ?? "").replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, n);
  function apprCard(i){
    const d = i.decision, imgs = apprImgs(i), shot = apprIsShot(i), draft = apprDraft.get(i._id) || {open: false, text: ""};
    const g = groups().find(x => x.key === (planList().some(r => r.key === i.release) ? i.release : "backlog"));
    const hasChange = d.options.some(o => /change/i.test(o.label || ""));
    const opts = d.options.map((o, k) => `<button type="button" class="appr-b${o.recommended ? " rec" : ""}" data-ak="${k}" data-ai="${esc(i._id)}">${o.recommended ? '<span class="appr-rec">Recommended</span>' : ""}<b>${esc(o.label)}</b>${o.detail ? `<small>${esc(o.detail)}</small>` : ""}</button>`).join("")
      + (hasChange ? "" : `<button type="button" class="appr-b" data-ak="other" data-ai="${esc(i._id)}"><b>${shot ? "Changes needed" : "Something else"}</b><small>${shot ? "Say what to change, then send." : "Say what should happen instead."}</small></button>`);
    const shots = imgs.length ? `<div class="appr-shots">${imgs.slice(0, 4).map((im, k) => `<button type="button" class="appr-shot" data-lb="${esc(i._id)}" data-li="${k}" aria-label="Enlarge screenshot ${k + 1} of ${imgs.length}: ${esc(im.alt || im.caption || i.ref)}"><img src="/_blob/${esc(im.id)}" alt="${esc(im.alt || im.caption || "Screenshot")}" loading="lazy"><span>${esc(im.caption || im.alt || "")}</span></button>`).join("")}${imgs.length > 4 ? `<span class="appr-more">${imgs.length - 4} more, open one to step through</span>` : ""}</div>` : "";
    return `<article class="appr-c${imgs.length ? "" : " noimg"}${shot ? " shot" : ""}" data-ac="${esc(i._id)}">${shots}<div>
      <div class="appr-meta"><span class="ref">${esc(i.ref)}</span><span class="appr-kind">${shot ? "Screenshot approval" : "Decision"}</span><span>${esc(g ? g.name : relName(i.release))}</span>${typeof i.minutes === "number" && i.minutes ? `<span>${esc(hm(i.minutes))}</span>` : ""}</div>
      <h3 class="appr-q">${esc(d.question || "Which way should this go?")}</h3>
      <p class="appr-t">${esc(i.task || "")}</p>${d.context ? `<p class="appr-ctx">${esc(d.context)}</p>` : ""}
      <div class="appr-acts">${opts}</div>
      <div class="appr-note" data-an="${esc(i._id)}" ${draft.open ? "" : "hidden"}><label class="sub" for="an-${esc(i._id)}">${shot ? "What should change" : "What should happen instead"}</label><textarea id="an-${esc(i._id)}" maxlength="1000">${esc(draft.text)}</textarea><div class="row"><button type="button" class="btn sm" data-asend="${esc(i._id)}">Send</button><button type="button" class="btn ghost sm" data-acancel="${esc(i._id)}">Cancel</button></div></div>
    </div></article>`;
  }
  function renderAppr(){
    const panel = $("apprPanel"); if (!panel) return;
    const list = canWrite ? decList() : [];
    if (panel.contains(document.activeElement) && document.activeElement.tagName === "TEXTAREA") return;
    panel.hidden = !list.length && !apprPend; $("apprN").textContent = list.length;
    $("apprList").innerHTML = list.map(apprCard).join("");
    $("apprUndo").hidden = !apprPend;
  }
  async function apprFlush(){
    const p = apprPend; if (!p) return; apprPend = null; clearTimeout(p.t); $("apprUndo").hidden = true;
    const told = await tellClaude(p.text, $("apprPanel"));
    say(told ? `${p.ref} answered, Claude told` : `${p.ref} answered. Tell Claude in the conversation`);
  }
  async function apprAnswer(id, k, note){
    const it = items.find(x => x._id === id); if (!it || !db || !canWrite || !asks(it)) return;
    await apprFlush();
    const d = it.decision, label = k === "other" ? (apprIsShot(it) ? "Changes needed" : "Something else") : String(d.options[Number(k)]?.label || "");
    if (!label) return; const at = new Date().toISOString(), n = apprFlat(note, 1000), prev = it.state;
    try { await db.doc("items/" + id).update({state: "answered", decisionAnswer: {choice: String(k), label, note: n, at, question: d.question || "", via: "approvals panel"}}); }
    catch (err) { say(err?.code === "invalid_argument" ? "You do not have permission to change this board." : "That did not save. Try again."); return; }
    apprDraft.delete(id);
    const text = `${apprIsShot(it) ? "APPROVAL" : "DECISION"} ANSWERED ${it.ref} (${id}): ${apprFlat(d.question, 300)} Answer: ${label}${n ? ". Note: " + n : ""}. Act on it and update the item.`;
    apprPend = {id, ref: it.ref, prev, text, t: setTimeout(apprFlush, APPR_UNDO_MS)};
    $("apprUndoTxt").textContent = `${it.ref}: ${label}. Claude is told in 10 seconds.`; $("apprUndo").hidden = false; $("apprPanel").hidden = false;
  }
  $("apprUndoBtn").addEventListener("click", async () => {
    const p = apprPend; if (!p) return; apprPend = null; clearTimeout(p.t); $("apprUndo").hidden = true;
    try { await db.doc("items/" + p.id).update({state: p.prev, decisionAnswer: null}); say(`${p.ref} put back, nobody was told`); }
    catch (_) { say("That did not undo. Reload and check the item."); }
  });
  $("apprList").addEventListener("click", e => {
    const b = e.target.closest("[data-ak]"); if (b) {
      if (b.dataset.ak === "other") { const box = document.querySelector(`[data-an="${CSS.escape(b.dataset.ai)}"]`); apprDraft.set(b.dataset.ai, {open: true, text: apprDraft.get(b.dataset.ai)?.text || ""}); box.hidden = false; box.querySelector("textarea").focus(); return; }
      b.disabled = true; apprAnswer(b.dataset.ai, b.dataset.ak, ""); return;
    }
    const s = e.target.closest("[data-asend]"); if (s) { const id = s.dataset.asend, ta = document.getElementById("an-" + id); if (!ta.value.trim()) { ta.focus(); say("Say what should change first"); return; } s.disabled = true; apprAnswer(id, "other", ta.value); return; }
    const c = e.target.closest("[data-acancel]"); if (c) { apprDraft.delete(c.dataset.acancel); renderAppr(); return; }
    const l = e.target.closest("[data-lb]"); if (l) { const it = items.find(x => x._id === l.dataset.lb); if (it) openLb(apprImgs(it), Number(l.dataset.li)); }
  });
  $("apprList").addEventListener("input", e => { const ta = e.target.closest("textarea"); if (ta) apprDraft.set(ta.id.slice(3), {open: true, text: ta.value}); });
  function openLb(set, k){ lbSet = set; lbAt = k; showLb(); if (!$("lbDlg").open) $("lbDlg").showModal(); }
  function showLb(){
    const im = lbSet[lbAt]; if (!im) return;
    $("lbImg").src = "/_blob/" + im.id; $("lbImg").alt = im.alt || im.caption || "Screenshot";
    $("lbCap").textContent = `${lbAt + 1} of ${lbSet.length}${im.caption ? ": " + im.caption : ""}`;
    $("lbPrev").disabled = lbAt <= 0; $("lbNext").disabled = lbAt >= lbSet.length - 1;
  }
  $("lbPrev").addEventListener("click", () => { if (lbAt > 0) { lbAt--; showLb(); } });
  $("lbNext").addEventListener("click", () => { if (lbAt < lbSet.length - 1) { lbAt++; showLb(); } });
  $("lbClose").addEventListener("click", () => $("lbDlg").close());
  $("lbDlg").addEventListener("keydown", e => { if (e.key === "ArrowLeft") $("lbPrev").click(); else if (e.key === "ArrowRight") $("lbNext").click(); });
  addEventListener("pagehide", () => { if (apprPend) apprFlush(); });
  %s
"""


def _once(text, anchor):
    n = text.count(anchor)
    if n != 1:
        raise ValueError(f"anchor found {n} times, expected once: {anchor[:60]!r}")


def has(html):
    return BEGIN in html


def apply(html):
    """Add the Approvals panel to a page that does not have it. Refuses a page that already has it."""
    if has(html):
        raise ValueError("the page already has the Approvals panel")
    a_css = "</style>"
    a_hero = '<section class="panel hero" aria-label="Current release">'
    a_dlg = '<div class="tip" id="tip" hidden></div>'
    a_hook = "renderThreads(); renderDecQ(); }); }"
    a_js = "  setInterval(() => { if (!document.hidden) render(); }, 60000);"
    for a in (a_css, a_hero, a_dlg, a_hook, a_js):
        _once(html, a)
    html = html.replace(a_css, CSS + a_css, 1)
    html = html.replace(a_hero, PANEL.lstrip() + "  " + a_hero, 1)
    html = html.replace(a_dlg, DIALOG + a_dlg, 1)
    html = html.replace(a_hook, "renderThreads(); renderDecQ(); renderAppr(); }); }", 1)
    html = html.replace(a_js, JS % (BEGIN, END) + a_js, 1)
    return html
