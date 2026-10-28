// Renders the board page against a store held in one JSON file and reports what it drew (VH-584).
// Usage: node render_board.cjs <page.html> <store.json> <out dir> probe|shot|writes
//   store.json   {collection: {doc id: fields}}, with board/meta and board/settings under "board"
//   probe        prints one JSON line of what the page drew: brand, labels, pipeline nodes, chart lines, tab and release
//                text, the guide's jobs, the merge placeholder, and every page error
//   shot         full-page screenshots at 1280 and 400 pixels wide, plus the guide, as desktop.png, phone.png, guide.png;
//                BOARD_OPEN_FOLDS=1 opens the folded chart panels first, so a picture can show the charts
//   writes       presses Refresh, then marks the store's upload as passed, and prints the writes, the refused updates and the
//                store afterwards. The stub refuses an update to a document that does not exist with invalid_argument, as the
//                platform does (db.d.ts: update "REQUIRES the document to exist"), so a
//                board seeded without a document the page later updates fails here and not in front of the owner.
// Chromium is found as render_merge.cjs finds it; PLAYWRIGHT_CORE names playwright-core when node cannot find it from here.
const fs = require('fs'), path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const [PAGE, STORE, OUT_ARG, MODE = 'probe'] = process.argv.slice(2);
const OUT = path.resolve(OUT_ARG || '.');
function findChromium() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const bases = [process.env.PLAYWRIGHT_BROWSERS_PATH, '/opt/pw-browsers', process.env.HOME && path.join(process.env.HOME, '.cache', 'ms-playwright')].filter(Boolean);
  const layouts = [[/^chromium-/, ['chrome-linux', 'chrome']], [/^chromium-/, ['chrome-linux64', 'chrome']], [/^chromium_headless_shell-/, ['chrome-headless-shell-linux64', 'chrome-headless-shell']]];
  for (const base of bases) {
    if (!fs.existsSync(base)) continue;
    for (const [match, tail] of layouts) for (const dir of fs.readdirSync(base).filter(d => match.test(d)).sort().reverse()) {
      const exe = path.join(base, dir, ...tail); if (fs.existsSync(exe)) return exe;
    }
  }
  return null;
}
const store = JSON.parse(fs.readFileSync(STORE, 'utf8'));
for (const c of ['items', 'plan', 'gates', 'releases', 'accuracy', 'intake', 'threads', 'links', 'board']) store[c] = store[c] || {};
const stub = `(()=>{const store=${JSON.stringify(store)};const subs={};let n=1000;window.__writes=[];window.__rejected=[];window.__told=[];
const snap=c=>({docs:Object.entries(store[c]||{}).map(([id,d])=>({id,data:()=>d}))});
const one=p=>{const [c,id]=p.split('/');return {exists:!!(store[c]||{})[id],data:()=>(store[c]||{})[id]};};
const fire=(c,p)=>{(subs[c]||[]).forEach(f=>f(snap(c)));(subs[p]||[]).forEach(f=>f(one(p)));};
const db={collection:c=>({onSnapshot:f=>{(subs[c]=subs[c]||[]).push(f);f(snap(c));return()=>{}},
  add:async d=>{const id='n'+(n++);(store[c]=store[c]||{})[id]=d;window.__writes.push(['add',c+'/'+id]);fire(c,c+'/'+id);return{id}}}),
 doc:p=>{const [c,id]=p.split('/');return{onSnapshot:f=>{(subs[p]=subs[p]||[]).push(f);f(one(p));return()=>{}},
  update:async d=>{if(!(store[c]||{})[id]){window.__rejected.push(p);throw {code:'invalid_argument',message:'no document '+p};}
    window.__writes.push(['update',p]);store[c][id]=Object.assign({},store[c][id],JSON.parse(JSON.stringify(d)));fire(c,p)},
  set:async d=>{(store[c]=store[c]||{})[id]=JSON.parse(JSON.stringify(d));window.__writes.push(['set',p]);fire(c,p)},
  delete:async()=>{delete (store[c]||{})[id];window.__writes.push(['delete',p]);fire(c,p)}}}};
const comments={canSendToClaude:async()=>'available',sendToClaude:async m=>{window.__told.push(m.text)},anchorFor:async()=>({})};
window.__store=store;window.__db=db;
window.claude={use:async k=>k==='db'?db:k==='user'?{isOwner:async()=>true}:k==='comments'?comments:null};})();`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const exe = findChromium();
  if (!exe) { console.error('No Chromium found: set CHROME_PATH or PLAYWRIGHT_BROWSERS_PATH.'); process.exit(2); }
  const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const html = '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1"></head><body>' + fs.readFileSync(PAGE, 'utf8') + '</body></html>';
  fs.writeFileSync(path.join(OUT, '_render.html'), html);
  const open = async (w, h) => {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' }); const p = await ctx.newPage(); const errs = [];
    p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await p.clock.setFixedTime(new Date('2026-10-07T10:00:00Z')); await p.addInitScript(stub);
    await p.goto('file://' + path.join(OUT, '_render.html')); await p.waitForTimeout(1000);
    return { ctx, p, errs };
  };
  if (MODE === 'probe') {
    const { ctx, p, errs } = await open(1280, 900);
    const cur = await p.evaluate(() => Object.entries(window.__store.plan).find(([, x]) => x.status === 'current')?.[0]);
    if (cur) { await p.click(`.tab[data-k="${cur}"]`); await p.waitForTimeout(200); }
    const facts = await p.evaluate(() => {
      const t = s => document.querySelector(s)?.textContent ?? null;
      return {
        brand: t('#brand'), title: document.title, uploadLabel: t('#kUploadLbl'), uploadSub: t('#kUploadSub'),
        nodes: [...document.querySelectorAll('#pipe g')].map(g => g.getAttribute('aria-label')),
        uploadNode: !!document.querySelector('#pipe g[data-upload]'), pipeSrc: t('#pipeSrc'), pipeStale: document.getElementById('pipeSrc').classList.contains('stale'), refresh: t('#pipeRefresh'),
        histSub: t('#histSub'), roundLine: !!document.querySelector('#hist line.ref'),
        roundLabel: [...document.querySelectorAll('#hist text.lbl')].map(x => x.textContent).join(' | '),
        tabs: [...document.querySelectorAll('.tab')].map(x => x.textContent), heading: t('#views h2'),
        foot: [...document.querySelectorAll('#views tfoot td.lbl, #views tfoot td:first-child')].map(x => x.textContent),
        guideIntro: t('#howIntro'), guideJobs: [...document.querySelectorAll('#howJobs details')].map(d => d.dataset.job),
        guideText: t('#howJobs'), mergeHint: document.getElementById('mgTo')?.placeholder, popTitle: t('#upPopH'), detailLabel: t('#inDetailLbl')
      };
    });
    facts.errors = errs; console.log(JSON.stringify(facts)); await ctx.close();
  } else if (MODE === 'shot') {
    for (const [w, h, tag] of [[1280, 900, 'desktop'], [400, 900, 'phone']]) {
      const { ctx, p, errs } = await open(w, h);
      if (process.env.BOARD_OPEN_FOLDS) { await p.$$eval('details.fold', d => d.forEach(x => { x.open = true; })); await p.waitForTimeout(400); }
      await p.screenshot({ path: path.join(OUT, tag + '.png'), fullPage: true });
      if (tag === 'desktop') {
        await p.click('#howBtn'); await p.$$eval('#howDlg details', d => d.forEach(x => { x.open = true; })); await p.waitForTimeout(400);
        await (await p.$('#howDlg form')).screenshot({ path: path.join(OUT, 'guide.png') });
      }
      console.log(tag, 'page errors:', JSON.stringify(errs)); await ctx.close();
    }
  } else if (MODE === 'writes') {
    const { ctx, p, errs } = await open(1280, 900);
    const toast = () => p.$eval('#toast', e => e.textContent);
    await p.click('#pipeRefresh'); await p.waitForTimeout(300);
    const refreshed = await toast();
    let marked = null;
    if (await p.$('#pipe g[data-upload]')) {
      const rel = await p.evaluate(() => Object.values(window.__store.plan).find(x => x.status === 'current')?.name || '');
      await p.click('#pipe g[data-upload]'); await p.click('[data-up="pass"]');
      if (await p.isVisible('#upAck')) await p.check('#upAck');
      await p.fill('#upType', rel); await p.click('#upGo'); await p.waitForTimeout(800);
      marked = await toast();
    }
    const out = await p.evaluate(() => ({ writes: window.__writes, rejected: window.__rejected, told: window.__told, store: window.__store }));
    console.log(JSON.stringify({ refreshed, marked, ...out, errors: errs })); await ctx.close();
  }
  await b.close();
})();
