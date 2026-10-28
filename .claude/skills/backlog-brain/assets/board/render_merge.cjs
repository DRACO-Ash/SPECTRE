// Renders the board page's Merge into control (VH-377 B) against a board dump, and exercises it.
// Usage: node render_merge.cjs <page.html> <dump dir> <out dir> [shot|test]
// The dump dir holds the folders items, plan, accuracy, intake, threads, links and board (as ArtifactData writes them).
// Planted tasks (VH-901 the source, VH-902 the target, VH-903 in a shipped release, VH-950 and "VH-950 part 2") are added
// to the current release so the real board is never touched. Chromium is found the way e2e/harness.mjs finds it
// (CHROME_PATH, then PLAYWRIGHT_BROWSERS_PATH, /opt/pw-browsers and ~/.cache/ms-playwright); PLAYWRIGHT_CORE names the
// playwright-core folder when node cannot find it from this folder upwards. Test mode exits 1 on any failed check or page error.
// An update to a document that does not exist is refused with invalid_argument, as the platform refuses it (VH-584).
const fs = require('fs'), path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const [PAGE, DUMP, OUT_ARG, MODE = 'shot'] = process.argv.slice(2);
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
function dump(dir) { const o = {}; if (!fs.existsSync(dir)) return o; for (const f of fs.readdirSync(dir)) { if (!f.endsWith('.json')) continue; const x = JSON.parse(fs.readFileSync(path.join(dir, f))); o[f.slice(0, -5)] = x.data || x; } return o; }
const store = { items: dump(DUMP + '/items'), plan: dump(DUMP + '/plan'), gates: dump(DUMP + '/gates'), releases: dump(DUMP + '/releases'), accuracy: dump(DUMP + '/accuracy'), intake: dump(DUMP + '/intake'), threads: dump(DUMP + '/threads'), links: dump(DUMP + '/links'), board: { meta: dump(DUMP + '/board').meta || {} } };
const cur = Object.entries(store.plan).find(([, p]) => p.status === 'current')[0];
const shipped = Object.entries(store.plan).find(([, p]) => p.status === 'released')[0];
const NOTE902 = 'Owner asked for this on 2026-10-03.';
store.items['VH-901'] = { ref: 'VH-901', state: 'open', release: cur, minutes: 45, priority: 'med', order: 0, task: 'Planted sample: retire the legacy export writer and its CSV shape', note: 'Raised in the audit.' };
store.items['VH-902'] = { ref: 'VH-902', state: 'open', release: cur, minutes: 60, priority: 'high', order: 0, task: 'Planted sample: retire the legacy export writer, its CSV format and its tests', note: NOTE902 };
store.items['VH-903'] = { ref: 'VH-903', state: 'built', release: shipped, minutes: 30, priority: 'low', order: 0, task: 'Planted sample in a shipped release' };
store.items['VH-950'] = { ref: 'VH-950', state: 'open', release: cur, minutes: 20, priority: 'low', order: 0, task: 'Planted sample: the parent of a split' };
store.items['VH-950p2'] = { ref: 'VH-950 part 2', state: 'open', release: cur, minutes: 25, priority: 'low', order: 0, task: 'Planted sample: the second part of the split' };
const stub = `(()=>{const store=${JSON.stringify(store)};const subs={};let n=1000;
const snap=c=>({docs:Object.entries(store[c]||{}).map(([id,d])=>({id,data:()=>d}))});
const fire=c=>(subs[c]||[]).forEach(f=>f(c==='board'?{exists:true,data:()=>store.board.meta}:snap(c)));
const db={collection:c=>({onSnapshot:(f)=>{(subs[c]=subs[c]||[]).push(f);f(snap(c));return()=>{}},add:async d=>{const id='n'+(n++);(store[c]=store[c]||{})[id]=d;fire(c);return{id}}}),
doc:p=>{const [c,id]=p.split('/');return{onSnapshot:(f)=>{(subs[p]=subs[p]||[]).push(f);f({exists:!!store[c][id],data:()=>store[c][id]});return()=>{}},
update:async d=>{if(window.__fail===p){window.__fail=null;throw {code:'unavailable'}}if(!(store[c]||{})[id])throw {code:'invalid_argument'};window.__writes=(window.__writes||[]).concat([[p,JSON.parse(JSON.stringify(d))]]);store[c][id]=Object.assign(store[c][id]||{},d);if(c==='board'){(subs['board/meta']||[]).forEach(f=>f({exists:true,data:()=>store.board.meta}))}else fire(c)},
set:async d=>{store[c][id]=d;fire(c)},delete:async()=>{delete store[c][id];fire(c)}}}};
window.__store=store;window.__db=db;
window.claude={use:async n=>n==='db'?db:n==='user'?{isOwner:async()=>true}:null};})();`;
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const exe = findChromium();
  if (!exe) { console.error('No Chromium found: set CHROME_PATH or PLAYWRIGHT_BROWSERS_PATH.'); process.exit(2); }
  const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage(); const errs = [];
  page.on('pageerror', e => errs.push(e.message)); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.addInitScript(stub);
  const html = '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1"></head><body>' + fs.readFileSync(PAGE, 'utf8') + '</body></html>';
  fs.writeFileSync(path.join(OUT, '_render.html'), html);
  await page.goto('file://' + path.join(OUT, '_render.html')); await page.waitForTimeout(1200);
  await page.click(`.tab[data-k="${cur}"]`); await page.waitForTimeout(400);
  const rowShot = async (ref, file) => {
    const box = await page.$eval(`[data-mg="${ref}"]`, e => { e.scrollIntoView({ block: 'center' }); const t = e.closest('tr').getBoundingClientRect(); const n = e.closest('tr').nextElementSibling.getBoundingClientRect(); const tb = e.closest('table').getBoundingClientRect(); return { x: tb.left, y: t.top - 70, width: tb.width, height: n.bottom - t.top + 140 }; });
    await page.screenshot({ path: path.join(OUT, file), clip: { x: Math.max(0, box.x), y: Math.max(0, box.y), width: Math.min(box.width, page.viewportSize().width), height: box.height } });
  };
  const overflow = () => page.evaluate(() => { const w = document.querySelector('#views .tw'); return w ? w.scrollWidth - w.clientWidth : -1; });
  const redraw = () => page.evaluate(async () => { await window.__db.doc('board/meta').update({ updatedAt: new Date().toISOString() }); });
  if (MODE === 'shot') {
    await rowShot('VH-901', '1-row-desktop.png');
    await page.click('[data-mg="VH-901"]'); await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(OUT, '2a-dialog-empty-desktop.png') });
    await page.fill('#mgTo', 'VH-902'); await page.dispatchEvent('#mgTo', 'input'); await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(OUT, '2-dialog-desktop.png') });
    await page.fill('#mgTo', 'VH-999'); await page.click('#mgGo'); await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(OUT, '3-dialog-refused-desktop.png') });
    await page.fill('#mgTo', 'VH-902'); await page.click('#mgGo'); await page.waitForTimeout(500);
    const t = await page.$eval('[data-mg="VH-902"]', e => { e.scrollIntoView({ block: 'center' }); const r = e.closest('tr').getBoundingClientRect(), n = e.closest('tr').nextElementSibling.getBoundingClientRect(), tb = e.closest('table').getBoundingClientRect(); return { x: tb.left, y: r.top - 50, width: tb.width, height: n.bottom - r.top + 100 }; });
    await page.screenshot({ path: path.join(OUT, '4-target-after-desktop.png'), clip: t });
    await page.click('.tab[data-k="removed"]'); await page.waitForTimeout(400);
    const rm = await page.$eval('[data-restore="VH-901"]', e => { e.scrollIntoView({ block: 'center' }); const r = e.closest('tr').getBoundingClientRect(), n = e.closest('tr').nextElementSibling.getBoundingClientRect(), tb = e.closest('table').getBoundingClientRect(); return { x: tb.left, y: r.top - 60, width: tb.width, height: n.bottom - r.top + 80 }; });
    await page.screenshot({ path: path.join(OUT, '5-removed-tab-desktop.png'), clip: rm });
    await page.setViewportSize({ width: 400, height: 900 }); await page.click(`.tab[data-k="${cur}"]`); await page.waitForTimeout(400);
    await page.evaluate(() => document.querySelector('[data-mg="VH-902"]').scrollIntoView({ block: 'center' }));
    await page.screenshot({ path: path.join(OUT, '6-row-phone.png') });
    console.log('phone horizontal overflow:', await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth));
    await page.click('[data-mg="VH-902"]'); await page.fill('#mgTo', 'VH'); await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(OUT, '7-dialog-phone.png') });
    await page.click('#mgCancel'); await page.setViewportSize({ width: 1280, height: 900 });
    await page.click('#howBtn'); await page.waitForTimeout(300); await page.click('[data-job="merge"] summary'); await page.waitForTimeout(300);
    await page.$eval('[data-job="merge"]', e => e.scrollIntoView({ block: 'center' }));
    await page.screenshot({ path: path.join(OUT, '8-guide-desktop.png') });
    await page.keyboard.press('Escape'); await page.setViewportSize({ width: 800, height: 900 }); await page.waitForTimeout(300);
    await rowShot('VH-902', '9-row-800.png');
  }
  if (MODE === 'test') {
    // Each check states the value it expects, measured on the run that wrote it, and the script exits 1 on any mismatch.
    let bad = 0;
    const T = async (l, f, want) => { let got; try { got = await f(); } catch (e) { got = 'ERR ' + e.message.split('\n')[0]; }
      const ok = JSON.stringify(got) === JSON.stringify(want); bad += ok ? 0 : 1; console.log((ok ? 'ok   ' : 'FAIL ') + l + (ok ? '' : '\n     got  ' + JSON.stringify(got) + '\n     want ' + JSON.stringify(want))); };
    const S = () => page.evaluate(() => window.__store.items);
    const writes = () => page.evaluate(() => (window.__writes || []).filter(w => w[0].startsWith('items/')).map(w => w[0]));
    const focused = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.dataset.mg ? 'mg:' + a.dataset.mg : a.dataset.rm ? 'rm:' + a.dataset.rm : a.id || a.tagName) : null; });
    await T('live rows carry Merge into, beside Remove', async () => await page.$eval('[data-mg="VH-901"]', e => [e.textContent, e.nextElementSibling.dataset.rm, e.disabled]), ['Merge into', 'VH-901', false]);
    await T('the list offers every other task not in a shipped release', async () => { await page.click('[data-mg="VH-901"]'); return await page.$$eval('#mgList option', o => { const v = o.map(x => x.value.split(' · ')[0]); return [v.includes('VH-902'), v.includes('VH-901'), v.includes('VH-903')]; }); }, [true, false, false]);
    await T('the target line shows its price stays as it is', async () => { await page.fill('#mgTo', 'vh-902'); await page.dispatchEvent('#mgTo', 'input'); return await page.$eval('#mgInto', e => !e.hidden && e.textContent); },
      'Into VH-902, priced 1h, which stays as it is: Planted sample: retire the legacy export writer, its CSV format and its tests');
    await T('a ref holding a space is read whole, from the list or typed', async () => { const r = [];
      for (const v of ['VH-950 part 2 · Planted sample: the second part of the split', 'vh-950 part 2', 'VH-950 · Planted sample']) { await page.fill('#mgTo', v); await page.dispatchEvent('#mgTo', 'input'); r.push(await page.$eval('#mgInto', e => e.hidden ? null : e.textContent.split(',')[0])); }
      return r; }, ['Into VH-950 part 2', 'Into VH-950 part 2', 'Into VH-950']);
    await T('a ref followed by other words matches nothing', async () => { await page.fill('#mgTo', 'VH-902 whatever'); await page.dispatchEvent('#mgTo', 'input'); return await page.$eval('#mgInto', e => e.hidden); }, true);
    await T('an unknown ref is refused, announced, tied to the field, and nothing is written', async () => { await page.fill('#mgTo', 'VH-999'); await page.click('#mgGo'); await page.waitForTimeout(200);
      return [await page.$eval('#mgErr', e => !e.hidden && e.getAttribute('role') + ' | ' + e.textContent), await page.$eval('#mgTo', e => [e.getAttribute('aria-invalid'), e.getAttribute('aria-describedby')]), (await writes()).length]; },
      ['alert | Pick a task on the board by its ref. It cannot be this task or one in a shipped release.', ['true', 'mgErr'], 0]);
    await T('typing clears the error and its field state', async () => { await page.type('#mgTo', '1'); return [await page.$eval('#mgErr', e => e.hidden), await page.$eval('#mgTo', e => [e.getAttribute('aria-invalid'), e.getAttribute('aria-describedby')])]; }, [true, [null, null]]);
    await T('its own ref is refused', async () => { await page.fill('#mgTo', 'VH-901'); await page.click('#mgGo'); await page.waitForTimeout(200); return [await page.$eval('#mgErr', e => !e.hidden), (await writes()).length]; }, [true, 0]);
    await T('a half-saved merge leaves the record on the source, reports, and keeps the box open', async () => { await page.evaluate(() => { window.__fail = 'items/VH-902'; }); await page.fill('#mgTo', 'VH-902'); await page.click('#mgGo'); await page.waitForTimeout(300); const s = await S();
      return [await page.$eval('#mgDlg', e => e.open), await page.$eval('#mgErr', e => !e.hidden && e.textContent), s['VH-901'].state, s['VH-901'].mergedInto, s['VH-902'].note]; },
      [true, 'That did not fully save. Press Merge again to finish it: nothing is written twice.', 'removed', 'VH-902', NOTE902]);
    await T('pressing Merge again finishes it: one line on the target, its minutes alone', async () => { await page.click('#mgGo'); await page.waitForTimeout(400); const s = await S(); const day = s['VH-901'].removedAt.slice(0, 10);
      return [s['VH-901'].state, s['VH-901'].removedFrom, s['VH-901'].removedState, (s['VH-902'].note.match(/VH-901 merged in/g) || []).length, s['VH-902'].minutes, s['VH-902'].note === `${NOTE902} ${day}: VH-901 merged in; its minutes were not added.`, await page.$eval('#mgDlg', e => e.open)]; },
      ['removed', cur, 'open', 1, 60, true, false]);
    await T('the source is written before the target, and each once', async () => await writes(), ['items/VH-901', 'items/VH-902']);
    await T('focus lands on the kept task, not the page body', async () => { await page.waitForTimeout(100); return await focused(); }, 'mg:VH-902');
    await T('the removed row says what it was merged into', async () => { await page.click('.tab[data-k="removed"]'); await page.waitForTimeout(300); return await page.$eval('[data-restore="VH-901"]', e => e.closest('td').textContent.replace(/\s+/g, ' ').trim()); },
      `${store.plan[cur].name}, merged into VH-902 Restore Delete for good`);
    await T('a removed row has no Merge into', async () => await page.$$eval('[data-mg="VH-901"]', e => e.length), 0);
    await T('Restore takes the line off the kept task and puts the source back', async () => { await page.click('[data-restore="VH-901"]'); await page.waitForTimeout(400); const s = await S(); return [s['VH-901'].state, s['VH-901'].release, s['VH-901'].mergedInto, s['VH-902'].note]; }, ['open', cur, null, NOTE902]);
    await T('a source another viewer removed meanwhile is refused and nothing more is written', async () => {
      await page.click(`.tab[data-k="${cur}"]`); await page.waitForTimeout(300); await page.click('[data-mg="VH-950"]'); const before = (await writes()).length;
      await page.evaluate(async () => { await window.__db.doc('items/VH-950').update({ state: 'removed', removedAt: new Date().toISOString(), removedFrom: 'x', removedState: 'open' }); });
      await page.fill('#mgTo', 'VH-902'); await page.click('#mgGo'); await page.waitForTimeout(300);
      return [await page.$eval('#mgErr', e => !e.hidden && e.textContent), (await writes()).length - before, (await S())['VH-902'].note]; },
      ['VH-950 has been removed or merged since this box opened. Close it and check the board.', 1, NOTE902]);
    await T('after a redraw while the box is open, Cancel gives focus back to the opener', async () => { await page.click('#mgCancel'); await page.waitForTimeout(100);
      await page.click('[data-mg="VH-901"]'); await redraw(); await page.waitForTimeout(200); await page.click('#mgCancel'); await page.waitForTimeout(150); return await focused(); }, 'mg:VH-901');
    await T('Remove gives focus back the same way', async () => { await page.click('[data-rm="VH-902"]'); await redraw(); await page.waitForTimeout(200); await page.click('#rmCancel'); await page.waitForTimeout(150); return await focused(); }, 'rm:VH-902');
    // Measured 2026-10-07 on a machine without Segoe UI, Helvetica or Arial: the page's stack falls to system-ui, which resolved to DejaVu Sans,
    // a wider face than Arial, and the table overflowed by 17 px at 800 and 37 px at 960 (nothing else differed). The width is checked in an
    // Arial-metric face so the verdict does not depend on which font a machine falls back to; Arial is a conservative stand-in for Segoe UI, not the same face.
    await T('the release table fits its panel at 800, 960 and 1280 pixels', async () => { const r = [];
      await page.addStyleTag({ content: 'html,body,button,input,select,textarea{font-family:"Liberation Sans",Arial,sans-serif !important}' });
      for (const w of [800, 960, 1280]) { await page.setViewportSize({ width: w, height: 900 }); await page.waitForTimeout(250); r.push(await overflow()); }
      return r.map(x => x <= 1); }, [true, true, true]);
    await T('every dialog error is announced', async () => await page.$$eval('dialog p.err', e => e.every(x => x.getAttribute('role') === 'alert') && e.length), 5);
    console.log(bad ? `${bad} check(s) failed` : 'all checks hold'); process.exitCode = bad || errs.length ? 1 : 0;
  }
  console.log('page errors:', JSON.stringify(errs)); await b.close();
})();
