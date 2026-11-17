/* SPECTRE first-party script: SPECTRE Orbital Watch, the mission game on the training page (SPC-248).
 *
 * The campaign, alert, HUD and debrief are server-rendered fragments (templates/partials/mission_*.html) that htmx
 * lands; this file adds what markup cannot: the stage that swaps the campaign for an alert or a debrief, Take the
 * watch (the Console tab and the HUD beside its frame, or over it below 1680 px), the points burst, combo and tone
 * when an objective is met, the clock against par, the score, the hint's spotlight drawn inside the same-origin
 * console frame, the star reveal and the stars flying home, opt-in sound, where focus goes, what an error response
 * shows, and keeping what the operator typed when the HUD is replaced by a poll.
 *
 * Every motion stops under prefers-reduced-motion (here and in static/css/mission.css); a reward then shows still.
 * Sound is off until the operator turns it on; the tones are generated with WebAudio, so there are no audio files.
 * No inline script or handler anywhere: every control asks for its behaviour through the data-* registries in
 * core.js (SPC-199).
 */
(function () {
  'use strict';

  var RUNNING_KEY = 'spectre-mission-running';
  var COLLAPSED_KEY = 'spectre-mission-hud-collapsed';
  var SOUND_KEY = 'spectre-mission-sound';
  var MISSION_PATH = '/training/m/';
  /* How long after the console frame's last request the HUD is asked again: short, so a condition met in the
     console ticks well inside a second, and long enough to fold a burst of requests into one. */
  var POKE_DELAY_MS = 150;
  var BURST_MS = 1400;
  var STILL_REWARD_MS = 2200;
  var PEEK_MS = 2600;
  var ON_WATCH_MS = 1000;
  var STAMP_MS = 3200;
  var STAR_FIRST_MS = 450;
  var STAR_GAP_MS = 700;
  var COUNT_MS = 700;
  var FLIGHT_MS = 750;
  var NOTE_S = 0.11;
  var MET_NOTES = [659.25, 987.77];
  var COMPLETE_NOTES = [523.25, 659.25, 783.99, 1046.5];
  var STAR_NOTE = [880];
  var COMBO_STEP = Math.pow(2, 2 / 12);   /* each link in a combo plays a whole tone higher */
  var COMBO_TOP = 5;
  var OFFSET_RE = /([zZ]|[+-]\d\d:?\d\d)$/;
  /* The status a HUD request answers when its mission is no longer running, and those a start is refused with. */
  var ENDED = [404, 409];
  var REFUSED = [403, 404, 409];

  var motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var overlayQuery = window.matchMedia ? window.matchMedia('(max-width: 1679px)') : null;

  function motionOff() { return Boolean(motionQuery && motionQuery.matches); }
  function overlayMode() { return Boolean(overlayQuery && overlayQuery.matches); }
  function byId(id) { return document.getElementById(id); }
  function shown(el) { return Boolean(el) && el.offsetParent !== null; }

  /* ── Storage: refused storage (a locked-down browser) leaves the defaults, never an error ── */
  function store(kind) {
    try { return window[kind]; } catch (e) { return null; }
  }
  function readStore(kind, key) {
    var s = store(kind);
    try { return s ? s.getItem(key) : null; } catch (e) { return null; }
  }
  function writeStore(kind, key, value) {
    var s = store(kind);
    if (!s) { return; }
    try {
      if (value === null) { s.removeItem(key); } else { s.setItem(key, value); }
    } catch (e) { /* refused: nothing to keep */ }
  }

  /* ── Sound: off by default, one toggle, short tones ── */
  var audio = null;

  function soundOn() { return readStore('localStorage', SOUND_KEY) === 'on'; }

  function audioContext() {
    if (audio) { return audio; }
    var Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) { return null; }
    audio = new Ctor();
    return audio;
  }

  function note(ctx, freq, at) {
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(freq, at);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.18, at + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + NOTE_S);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(at);
    osc.stop(at + NOTE_S + 0.02);
  }

  function tone(notes, lift) {
    if (!soundOn()) { return; }
    var ctx = audioContext();
    if (!ctx) { return; }
    if (ctx.state === 'suspended' && ctx.resume) { ctx.resume(); }
    var scale = lift || 1;
    notes.forEach(function (freq, i) { note(ctx, Math.round(freq * scale * 100) / 100, ctx.currentTime + i * NOTE_S); });
  }

  function showSoundState() {
    var btn = byId('mission-sound-toggle');
    if (!btn) { return; }
    var on = soundOn();
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    var state = btn.querySelector('.mission-sound__state');
    if (state) { state.textContent = on ? 'on' : 'off'; }
  }

  SPECTRE.action('missionSound', function () {
    writeStore('localStorage', SOUND_KEY, soundOn() ? null : 'on');
    showSoundState();
    tone(MET_NOTES);   /* turning it on is a click, which lets the browser start the audio */
  });

  /* ── Small helpers ── */
  var announcing = false;

  /* Said in the live region. Two in the same tick (an objective met, then all met) are read together, the second
     after the first, rather than the second overwriting the first. */
  function announce(text) {
    var live = byId('mission-announce');
    if (!live) { return; }
    if (announcing) {
      live.textContent += ' ' + text;
      return;
    }
    live.textContent = text;
    announcing = true;
    setTimeout(function () { announcing = false; }, 0);
  }

  function showTab(id) {
    if (typeof window.trainingTab === 'function') { window.trainingTab(id); }
  }

  /* Focus moves by script only while the operator is not working in the console frame: never out of it. */
  function mayMoveFocus() {
    var active = document.activeElement;
    return !active || active.tagName !== 'IFRAME';
  }

  /* Into the HUD while it is folded away (inert), focus goes to its handle instead. */
  function focusQuietly(el) {
    if (!el || !mayMoveFocus()) { return; }
    var dock = byId('mission-hud-dock');
    var target = dock && dock.inert && dock.contains(el) ? byId('mission-hud-handle') : el;
    target.focus({ preventScroll: true });
  }

  function focusHeading(root) {
    focusQuietly(root.querySelector('h2[tabindex]'));
    var main = byId('training-main');
    if (main) { main.scrollTop = 0; }
  }

  function clockText(seconds) {
    var s = Math.max(0, Math.floor(seconds));
    var rest = s % 60;
    return Math.floor(s / 60) + ':' + (rest < 10 ? '0' : '') + rest;
  }

  function countUp(el, from, to) {
    if (to <= from || motionOff()) { el.textContent = String(to); return; }
    var start = performance.now();
    function step(now) {
      var t = Math.min(1, (now - start) / COUNT_MS);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = String(Math.round(from + (to - from) * eased));
      if (t < 1 && document.contains(el)) { requestAnimationFrame(step); }
    }
    el.textContent = String(from);
    requestAnimationFrame(step);
  }

  function objectiveText(li) {
    var p = li.querySelector('.mission-objective__text');
    return p && p.firstChild ? p.firstChild.textContent.trim().replace(/\.$/, '') : '';
  }

  function fxPoint(el, dx, dy) {
    var layer = byId('mission-fx');
    if (!shown(layer)) { return null; }
    var from = el.getBoundingClientRect();
    var box = layer.getBoundingClientRect();
    return { layer: layer, x: from.right - box.left + dx, y: from.top - box.top + from.height / 2 + dy };
  }

  /* A floating "+N" (or "-N"), still under reduced motion: the reward stays, only the motion goes. */
  function floatText(anchor, text, kind, dy) {
    var b = document.createElement('span');
    b.className = 'mission-burst mission-burst--' + kind + (motionOff() ? ' is-still' : '');
    b.textContent = text;
    var at = fxPoint(anchor, -140, (dy || 0) - 16);
    if (at) {
      b.style.left = at.x + 'px';
      b.style.top = at.y + 'px';
      at.layer.appendChild(b);
    } else {
      anchor.appendChild(b);
    }
    setTimeout(function () { b.remove(); }, motionOff() ? STILL_REWARD_MS : BURST_MS);
  }

  /* ── The stage: an alert or a debrief takes the Campaign tab; clearing it brings the map back ── */
  function setStage(kind) {
    var panel = byId('tpanel-campaign');
    if (panel) { panel.dataset.stage = kind; }
  }

  function clearStage() {
    var stage = byId('mission-stage');
    if (stage) { stage.innerHTML = ''; }
    setStage('');
  }

  /* ── The campaign map: fetched again on training-changed while it shows, else when next shown ── */
  var campaignStale = false;

  function refreshCampaign() {
    var region = byId('mission-campaign');
    if (!region) { return; }
    campaignStale = false;
    window.htmx.trigger(region, 'mission-campaign-refresh');
  }

  function aimedAtCampaign(el) {
    return Boolean(el && el.getAttribute) && el.getAttribute('hx-target') === '#mission-campaign';
  }

  document.addEventListener('training-changed', function (event) {
    /* A response that lands the campaign itself (Stand down, Abandon) needs no second fetch. */
    if (aimedAtCampaign(event.target)) { campaignStale = false; return; }
    if (shown(byId('tpanel-campaign'))) { refreshCampaign(); } else { campaignStale = true; }
  });

  /* ── The running mission: the HUD in its dock, and what survives a reload of the page ── */
  var memory = freshMemory(null);
  var bestsAtStart = {};

  function freshMemory(missionId) {
    return {
      missionId: missionId, score: null, hints: null, celebrated: {}, hinted: {}, statuses: null, signature: '',
      complete: false, combo: 0, focusNext: false, focusHeading: false, onWatch: false, quiet: false, hintCost: 0,
      notes: {}, error: null, landing: '', postObjective: null
    };
  }

  function running() {
    try { return JSON.parse(readStore('sessionStorage', RUNNING_KEY) || 'null'); } catch (e) { return null; }
  }

  function hudWrap() { return byId('mission-hud-wrap'); }

  function startHud(info, how) {
    var dock = byId('mission-hud-dock');
    if (!dock || !info || !info.id) { return; }
    writeStore('sessionStorage', RUNNING_KEY, JSON.stringify({ id: info.id, title: info.title || '' }));
    memory = freshMemory(info.id);
    memory.focusHeading = how === 'watch';
    memory.onWatch = how === 'watch';
    memory.quiet = how === 'restore';
    var wrap = hudWrap();
    if (wrap) { wrap.hidden = false; }
    setCollapsed(readStore('sessionStorage', COLLAPSED_KEY) === info.id, false);
    window.htmx.ajax('GET', MISSION_PATH + encodeURIComponent(info.id) + '/hud', { target: dock, swap: 'innerHTML' });
  }

  function stopHud() {
    clearSpotlight();
    writeStore('sessionStorage', RUNNING_KEY, null);
    writeStore('sessionStorage', COLLAPSED_KEY, null);
    memory = freshMemory(null);
    var dock = byId('mission-hud-dock');
    if (dock) { dock.innerHTML = ''; }
    var wrap = hudWrap();
    if (wrap) { wrap.hidden = true; }
  }

  /* The server says the mission is not running (ended elsewhere, or in another tab): say so where the HUD was. */
  function hudEnded(reason) {
    var said = reason || 'This mission ended.';
    var quiet = memory.quiet;
    stopHud();
    if (quiet) { return; }
    var wrap = hudWrap();
    var dock = byId('mission-hud-dock');
    if (!wrap || !dock) { return; }
    wrap.hidden = false;
    setCollapsed(false, false);
    var card = document.createElement('div');
    card.className = 'mission-hud__ended';
    var text = document.createElement('p');
    text.textContent = said;
    var back = document.createElement('button');
    back.type = 'button';
    back.id = 'mission-ended-back';
    back.className = 'mission-btn mission-btn--primary';
    back.dataset.action = 'missionEndedBack';
    back.textContent = 'Back to the campaign';
    card.appendChild(text);
    card.appendChild(back);
    dock.appendChild(card);
    announce(said);
  }

  SPECTRE.action('missionEndedBack', function () {
    stopHud();
    showTab('campaign');
  });

  SPECTRE.action('missionTakeWatch', function (btn) {
    clearStage();
    startHud({ id: btn.dataset.missionId, title: btn.dataset.missionTitle || '' }, 'watch');
    showTab('console');
  });

  /* Back to a running mission: from the campaign's strip, or its node. */
  SPECTRE.action('missionResume', function (btn) {
    var hud = byId('mission-hud');
    if (!hud || hud.dataset.missionId !== btn.dataset.missionId) {
      startHud({ id: btn.dataset.missionId, title: btn.dataset.missionTitle || '' }, 'watch');
    }
    showTab('console');
  });

  /* Stand down on the alert, or Abandon on the HUD: the campaign has landed in its place. Focus goes to the
     mission's node, where the operator was before starting it. */
  function focusNode(id) {
    var node = document.querySelector('.mission-node[data-mission-id="' + CSS.escape(id) + '"] .mission-node__face');
    if (!node) { return; }
    if (!node.matches('button')) { node.tabIndex = -1; }
    node.focus({ preventScroll: true });
  }

  SPECTRE.afterRequest('missionEnded', function (el, event) {
    if (!event.detail.successful) { return; }
    var holder = el.closest('[data-mission-id]');
    var id = holder ? holder.dataset.missionId : '';
    stopHud();
    clearStage();
    showTab('campaign');
    setTimeout(function () { focusNode(id); }, 0);
  });

  SPECTRE.init('missionAlert', function (alertEl) {
    var id = alertEl.dataset.missionId;
    var node = document.querySelector('.mission-node[data-mission-id="' + id + '"]');
    if (node) {
      bestsAtStart[id] = { stars: Number(node.dataset.stars) || 0, points: Number(node.dataset.bestPoints) || 0 };
    }
    stopHud();
    setStage('alert');
    showTab('campaign');
    focusHeading(alertEl);
  });

  /* ── The HUD over the frame below 1680 px: collapsible, remembered for the mission, peeking on a reward ── */
  var peekTimer = null;

  function setCollapsed(collapsed, remember) {
    var wrap = hudWrap();
    var handle = byId('mission-hud-handle');
    var dock = byId('mission-hud-dock');
    if (!wrap || !handle || !dock) { return; }
    var inOverlay = overlayMode();
    wrap.dataset.collapsed = collapsed ? 'true' : 'false';
    handle.setAttribute('aria-expanded', collapsed && inOverlay ? 'false' : 'true');
    var verb = handle.querySelector('.mission-hud-handle__verb');
    if (verb) { verb.textContent = collapsed ? 'Show the mission HUD' : 'Hide the mission HUD'; }
    dock.inert = collapsed && inOverlay;
    if (remember && memory.missionId) {
      writeStore('sessionStorage', COLLAPSED_KEY, collapsed ? memory.missionId : null);
    }
  }

  function collapsed() {
    var wrap = hudWrap();
    return Boolean(wrap) && wrap.dataset.collapsed === 'true' && overlayMode();
  }

  SPECTRE.action('missionHudToggle', function (handle) {
    var close = !collapsed();
    var dock = byId('mission-hud-dock');
    var focusInside = dock && dock.contains(document.activeElement);
    setCollapsed(close, true);
    if (close && focusInside) { handle.focus(); }
  });

  function peek() {
    var wrap = hudWrap();
    if (!wrap || !collapsed()) { return; }
    wrap.dataset.peek = 'true';
    clearTimeout(peekTimer);
    peekTimer = setTimeout(function () { delete wrap.dataset.peek; }, PEEK_MS);
  }

  /* Crossing 1680 px moves the HUD between docked and overlaid; its collapsed state holds for the overlay. */
  if (overlayQuery && overlayQuery.addEventListener) {
    overlayQuery.addEventListener('change', function () {
      var wrap = hudWrap();
      setCollapsed(Boolean(wrap) && wrap.dataset.collapsed === 'true', false);
    });
  }

  function updateHandle(hud) {
    var count = byId('mission-hud-handle-count');
    if (count) { count.textContent = hud.dataset.met + '/' + hud.dataset.total; }
  }

  /* ── The HUD, each time a response lands ── */
  function signature(hud) {
    var parts = [hud.dataset.score];
    hud.querySelectorAll('[data-objective-id]').forEach(function (li) {
      parts.push(li.dataset.objectiveId + ':' + li.dataset.status + ':' + (li.dataset.hintShown || ''));
    });
    return parts.join('|');
  }

  function statuses(hud) {
    var found = {};
    hud.querySelectorAll('[data-objective-id]').forEach(function (li) { found[li.dataset.objectiveId] = li; });
    return found;
  }

  /* A combo is objectives met back to back with no hint and no miss between them. */
  function comboAfter(hud, misses) {
    var hints = Number(hud.dataset.hintsUsed) || 0;
    if (misses || (memory.hints !== null && hints > memory.hints)) { memory.combo = 0; }
    memory.hints = hints;
  }

  function celebrate(hud) {
    var fresh = [];
    hud.querySelectorAll('[data-just-met="true"]').forEach(function (li) {
      var id = li.dataset.objectiveId;
      if (memory.celebrated[id]) { return; }
      memory.celebrated[id] = true;
      fresh.push(li);
    });
    if (!fresh.length) { return; }
    fresh.forEach(function (li, i) {
      memory.combo += 1;
      floatText(li, '+' + (li.dataset.pointsAwarded || '0'), 'gain', i * 40);
      if (memory.combo > 1) { floatText(li, 'Combo x' + memory.combo, 'combo', i * 40 + 34); }
    });
    tone(MET_NOTES, Math.pow(COMBO_STEP, Math.min(memory.combo, COMBO_TOP) - 1));
    peek();
    announce(fresh.map(function (li) {
      return 'Objective met: ' + objectiveText(li) + '. Plus ' + (li.dataset.pointsAwarded || '0') + ' score.';
    }).join(' '));
  }

  function missesSince(hud) {
    var now = statuses(hud);
    var before = memory.statuses;
    memory.statuses = {};
    Object.keys(now).forEach(function (id) { memory.statuses[id] = now[id].dataset.status; });
    if (!before) { return []; }
    return Object.keys(now).filter(function (id) {
      return now[id].dataset.status === 'failed' && before[id] !== 'failed';
    }).map(function (id) { return now[id]; });
  }

  function announceMisses(misses) {
    if (!misses.length) { return; }
    announce(misses.map(function (li) { return 'Missed: ' + objectiveText(li) + '.'; }).join(' '));
  }

  function showScore(hud) {
    var out = hud.querySelector('#mission-score-value');
    var to = Number(hud.dataset.score) || 0;
    var from = memory.score === null ? to : memory.score;
    var hintTaken = memory.hints !== null && (Number(hud.dataset.hintsUsed) || 0) > memory.hints;
    memory.score = to;
    if (!out) { return; }
    if (to > from) { out.classList.add('is-rising'); }
    countUp(out, from, to);
    if (hintTaken && memory.hintCost) { floatText(out, '-' + memory.hintCost, 'cost', 0); }
    memory.hintCost = 0;
  }

  function revealHints(hud) {
    hud.querySelectorAll('[data-hint-shown="true"]').forEach(function (li) {
      var id = li.dataset.objectiveId;
      if (memory.hinted[id]) { return; }
      memory.hinted[id] = true;
      if (li.dataset.spotlight && li.dataset.status === 'open' && memory.statuses !== null) {
        spotlightFor(id, li.dataset.spotlight);
      }
    });
  }

  /* What the spotlight could not show, written under the objective's hint as well as said: it stays until the
     objective is settled or the spotlight finds the control itself. Re-applied after each HUD response. */
  function showNotes(hud) {
    Object.keys(memory.notes).forEach(function (id) {
      var li = hud.querySelector('[data-objective-id="' + CSS.escape(id) + '"]');
      var hint = li ? li.querySelector('.mission-hint') : null;
      if (!li || li.dataset.status !== 'open' || !hint) { delete memory.notes[id]; return; }
      var note = hint.querySelector('.mission-hint__note') || document.createElement('p');
      note.className = 'mission-hint__note';
      note.textContent = memory.notes[id];
      if (!note.parentNode) { hint.appendChild(note); }
    });
  }

  function spotlightFor(id, selector) {
    var said = drawSpotlight(selector);
    if (said) { memory.notes[id] = said; } else { delete memory.notes[id]; }
    var hud = byId('mission-hud');
    if (hud) { showNotes(hud); }
  }

  /* After an answer, a choice or a hint: the next open field, or Debrief when nothing is left open. */
  function nextFocus(hud) {
    var open = hud.querySelectorAll('[data-status="open"]');
    for (var i = 0; i < open.length; i++) {
      var field = open[i].querySelector('input[type="text"], input[type="radio"]');
      if (field) { return field; }
    }
    return open.length ? hud.querySelector('#mission-hud-title') : hud.querySelector('#mission-finish');
  }

  function placeFocus(hud) {
    if (memory.focusHeading) {
      memory.focusHeading = false;
      focusQuietly(hud.querySelector('#mission-hud-title'));
    } else if (memory.focusNext) {
      memory.focusNext = false;
      focusQuietly(nextFocus(hud));
    }
  }

  function allMet(hud) {
    if (hud.dataset.allMet !== 'true' || memory.complete) { return; }
    memory.complete = true;
    announce('All objectives met. Debrief when ready.');
    var dock = byId('mission-hud-dock');
    if (!dock || dock.contains(document.activeElement) || document.activeElement === document.body) {
      focusQuietly(hud.querySelector('#mission-finish'));
    }
  }

  function onWatch() {
    if (!memory.onWatch) { return; }
    memory.onWatch = false;
    var flash = byId('mission-on-watch');
    if (!flash) { return; }
    flash.hidden = false;
    setTimeout(function () { flash.hidden = true; }, ON_WATCH_MS);
  }

  SPECTRE.init('missionHud', function (hud) {
    hud.addEventListener('htmx:beforeSwap', detachedSwap);
    if (memory.missionId !== hud.dataset.missionId) { memory = freshMemory(hud.dataset.missionId); }
    memory.quiet = false;
    var sig = signature(hud);
    /* The spotlight lasts until progress changes, not until the next poll, which may land any moment. */
    if (memory.signature && sig !== memory.signature) { clearSpotlight(); }
    memory.signature = sig;
    var misses = missesSince(hud);
    showScore(hud);
    comboAfter(hud, misses.length > 0);
    celebrate(hud);
    announceMisses(misses);
    revealHints(hud);
    showNotes(hud);
    keepError(hud);
    updateHandle(hud);
    onWatch();
    placeFocus(hud);
    allMet(hud);
    tickClock();
  });

  /* ── The mission clock against par ── */
  function startedAt(iso) {
    if (!iso) { return Number.NaN; }
    return Date.parse(OFFSET_RE.test(iso) ? iso : iso + 'Z');   /* a bare ISO time is UTC, as the server keeps it */
  }

  function tickClock() {
    var box = byId('mission-clock');
    if (!box) { return; }
    var start = startedAt(box.dataset.startedAt);
    var par = Number(box.dataset.parSeconds) || 0;
    var elapsed = Number.isNaN(start) ? 0 : Math.max(0, (Date.now() - start) / 1000);
    var time = byId('mission-clock-time');
    if (time) { time.textContent = clockText(elapsed); }
    box.dataset.overPar = par > 0 && elapsed > par ? 'true' : 'false';
    var arc = box.querySelector('.mission-clock__arc');
    if (arc && par > 0) { arc.style.strokeDashoffset = String(100 - Math.min(100, (elapsed / par) * 100)); }
  }
  setInterval(tickClock, 1000);

  /* ── Requests: what is typed survives a poll, errors show in place, and polling rests while unseen ── */
  var carried = null;

  function snapshot(hud) {
    var kept = {};
    hud.querySelectorAll('input[id]:not([type="hidden"])').forEach(function (field) {
      if (field.type === 'radio') {
        if (field.checked) { kept[field.id] = { checked: true }; }
      } else if (field.value) {
        kept[field.id] = { value: field.value };
      }
    });
    return kept;
  }

  function restore(kept) {
    Object.keys(kept).forEach(function (id) {
      var field = byId(id);
      if (!field) { return; }
      if (kept[id].checked) { field.checked = true; return; }
      if (field.value) { return; }
      field.value = kept[id].value;
      if (document.activeElement === field) { field.setSelectionRange(field.value.length, field.value.length); }
    });
  }

  function isHudTarget(target) {
    return Boolean(target) && (target.id === 'mission-hud' || target.id === 'mission-hud-dock');
  }

  function isHudForm(elt) {
    return Boolean(elt) && elt.tagName === 'FORM' && /^mission-(answer|choose|hint)$/.test(elt.getAttribute('name') || '');
  }

  function consoleShowing() { return shown(byId('tpanel-console')); }

  function isHudPost(detail) {
    var config = detail.requestConfig || {};
    var path = detail.pathInfo ? detail.pathInfo.requestPath || '' : config.path || '';
    return String(config.verb || '').toLowerCase() === 'post' && path.indexOf(MISSION_PATH) === 0;
  }


  /* Posts the HUD has in flight, and when the poll in flight (if any) went out. A poll waits for both rather than
     racing them, so nothing is ever aborted; a poll gone 10 s without an answer no longer holds the next one. */
  var posting = 0;
  var pollSince = 0;
  var POLL_STALE_MS = 10000;

  function pollWaits() {
    var polling = pollSince && Date.now() - pollSince < POLL_STALE_MS;
    return document.hidden || !consoleShowing() || posting > 0 || Boolean(polling);
  }

  function isPoll(detail) {
    return Boolean(detail.elt) && detail.elt.id === 'mission-hud' && !isHudPost(detail);
  }

  /* A poll waits while the browser tab is hidden, the Console tab is not showing, or a request is in flight;
     showing the tab asks at once. */
  document.addEventListener('htmx:beforeRequest', function (event) {
    var elt = event.detail.elt;
    var xhr = event.detail.xhr;
    if (isPoll(event.detail)) {
      if (pollWaits()) { event.preventDefault(); return; }
      pollSince = Date.now();
      /* loadend, on the request itself: htmx's own afterRequest fires on an element a swap may have detached. */
      if (xhr) { xhr.addEventListener('loadend', function () { pollSince = 0; }); }
    }
    if (isHudPost(event.detail)) {
      posting += 1;
      if (xhr) { xhr.addEventListener('loadend', function () { posting = Math.max(0, posting - 1); }); }
    }
    if (isHudForm(elt)) {
      var objective = elt.querySelector('input[name="objective_id"]');
      memory.postObjective = objective ? objective.value : null;
      memory.error = null;               /* a new try: its own answer says whether there is still an error */
      memory.focusNext = true;
      var cost = elt.querySelector('[data-cost]');
      if (cost) { memory.hintCost = Number(cost.dataset.cost) || 0; }
    }
  });

  function status(event) { return event.detail.xhr ? event.detail.xhr.status : 0; }

  /* The ways a response can say the sign-in has ended: 401, HX-Redirect to the login page, or a redirect followed
     to it. Shown as a message, never as the login page inside the HUD. */
  function signedOut(xhr) {
    if (!xhr) { return false; }
    var redirect = xhr.getResponseHeader('HX-Redirect') || '';
    var landed = xhr.responseURL ? new URL(xhr.responseURL).pathname : '';
    return xhr.status === 401 || redirect.indexOf('/login') === 0 || landed === '/login';
  }

  function isMissionRequest(detail) {
    var path = detail.pathInfo ? detail.pathInfo.requestPath || '' : '';
    return path.indexOf(MISSION_PATH) === 0;
  }

  document.addEventListener('htmx:beforeOnLoad', function (event) {
    if (!isMissionRequest(event.detail) || !signedOut(event.detail.xhr)) { return; }
    event.preventDefault();
    var dock = byId('mission-hud-dock');
    if (dock) { dock.innerHTML = ''; }
    var wrap = hudWrap();
    if (wrap) { wrap.hidden = true; }
    clearSpotlight();
    var ended = byId('mission-session-ended');
    if (ended) { ended.hidden = false; }
  });

  var UNREACHABLE = 'Could not reach the server. Try again.';

  /* The HUD's alert line, written in place: nothing is swapped, so what was typed stays, and htmx re-enables the
     button the request disabled. */
  /* An error stays until the operator acts on its objective again: types in it, posts again, or it settles. Polls
     re-render the HUD without it, so it is kept here and written back after each one (keepError). One no
     objective owns (a failed poll) goes as soon as a poll is answered again. */
  function hudAlert(text, objective) {
    memory.error = { text: text, objective: objective || null };
    placeAlert(text);
  }

  function errorOwner(detail) {
    return isHudPost(detail) ? memory.postObjective : null;
  }

  function placeAlert(text) {
    var hud = byId('mission-hud');
    if (!hud) { return; }
    var line = byId('mission-hud-error');
    if (!line) {
      line = document.createElement('p');
      line.id = 'mission-hud-error';
      line.className = 'mission-hud__error';
      line.setAttribute('role', 'alert');
      hud.insertBefore(line, hud.querySelector('.mission-objectives'));
    }
    line.textContent = text;
  }

  function reasonIn(html) {
    try {
      var text = new DOMParser().parseFromString(String(html || ''), 'text/html').body.textContent || '';
      return text.replace(/\s+/g, ' ').trim().slice(0, 200);
    } catch (e) { return ''; }
  }

  function hudErrorSwap(event) {
    var code = status(event);
    if (code === 422) {
      event.detail.shouldSwap = true;    /* the HUD with its error line, in place */
      event.detail.isError = false;
    } else if (ENDED.indexOf(code) !== -1) {
      event.detail.shouldSwap = false;
      event.detail.isError = false;      /* expected: the mission is not running, which hudEnded says */
      hudEnded(reasonIn(event.detail.serverResponse));
    } else if (code === 403 || code >= 500) {
      event.detail.shouldSwap = false;
      event.detail.isError = false;
      hudAlert(UNREACHABLE, errorOwner(event.detail));
    }
  }

  function keepError(hud) {
    var landing = memory.landing;
    memory.landing = '';
    var line = hud.querySelector('#mission-hud-error');
    if (landing === 'post') {
      memory.error = line ? { text: line.textContent.trim(), objective: memory.postObjective } : null;
      return;
    }
    if (!memory.error) { return; }
    var owner = memory.error.objective;
    var li = owner ? hud.querySelector('[data-objective-id="' + CSS.escape(owner) + '"]') : null;
    if (!li || li.dataset.status !== 'open') { memory.error = null; return; }
    if (!line) { placeAlert(memory.error.text); }
  }

  /* Typing in the objective the error is about clears it. */
  document.addEventListener('input', function (event) {
    var owner = memory.error ? memory.error.objective : null;
    var li = event.target.closest ? event.target.closest('#mission-hud [data-objective-id]') : null;
    if (!owner || !li || li.dataset.objectiveId !== owner) { return; }
    memory.error = null;
    var line = byId('mission-hud-error');
    if (line) { line.remove(); }
  });

  /* Restart answers with the alert (a fresh run to take the watch on) or, if the server starts the run at once,
     the HUD: that one belongs in the dock. */
  function restartSwap(event) {
    var path = event.detail.pathInfo ? event.detail.pathInfo.requestPath || '' : '';
    var body = String(event.detail.serverResponse || '');
    if (!/\/restart$/.test(path) || body.indexOf('id="mission-hud"') === -1) { return; }
    var dock = byId('mission-hud-dock');
    if (!dock) { return; }
    memory = freshMemory(memory.missionId);
    event.detail.target = dock;
  }

  document.addEventListener('htmx:sendError', function (event) {
    if (isHudTarget(event.detail.target)) { hudAlert(UNREACHABLE, errorOwner(event.detail)); }
  });

  function stageErrorSwap(event) {
    var code = status(event);
    if (REFUSED.indexOf(code) === -1) { return; }
    event.detail.shouldSwap = true;      /* the server's reason, where the alert would have landed */
    event.detail.isError = false;
    var path = event.detail.pathInfo ? event.detail.pathInfo.requestPath || '' : '';
    if (/\/finish$/.test(path)) { stopHud(); }
  }

  function beforeSwap(event) {
    var target = event.detail.target;
    /* A post's answer lands on the HUD a poll put up meanwhile. A poll's answer for a HUD that has since been
       replaced, or removed by a debrief, has nowhere to go. */
    var current = byId('mission-hud');
    if (isHudTarget(target) && !document.body.contains(target) && current && isHudPost(event.detail)) {
      event.detail.target = current;
      target = current;
    } else if (isHudTarget(target) && !document.body.contains(target)) {
      event.detail.shouldSwap = false;
      event.detail.isError = false;
      return;
    }
    if (isHudTarget(target)) { hudErrorSwap(event); }
    if (target && target.id === 'mission-stage') {
      stageErrorSwap(event);
      restartSwap(event);
      target = event.detail.target;
    }
    var hud = byId('mission-hud');
    carried = isHudTarget(target) && hud && event.detail.shouldSwap ? snapshot(hud) : null;
    if (isHudTarget(target) && event.detail.shouldSwap) { memory.landing = isHudPost(event.detail) ? 'post' : 'poll'; }
  }

  document.addEventListener('htmx:beforeSwap', beforeSwap);

  /* htmx raises beforeSwap on the target, and an event on an element a swap has already detached never reaches the
     document: each HUD therefore answers for itself once it is gone, so a late answer is dropped or re-aimed rather
     than swapped into nowhere (htmx:swapError). */
  function detachedSwap(event) {
    if (!document.body.contains(event.currentTarget)) { beforeSwap(event); }
  }

  document.addEventListener('htmx:afterSwap', function (event) {
    if (carried) { restore(carried); }
    carried = null;
    if (event.detail.target && event.detail.target.id === 'mission-campaign') { campaignStale = false; }
  });

  /* ── The console frame: its requests ask the HUD again, and a hint draws its spotlight in it ── */
  var pokeTimer = null;

  function poke() {
    if (!byId('mission-hud')) { return; }
    clearTimeout(pokeTimer);
    pokeTimer = setTimeout(function () { window.htmx.trigger(document.body, 'mission-poke'); }, POKE_DELAY_MS);
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && consoleShowing()) { poke(); }
  });

  function frameDoc() {
    var frame = byId('training-console-frame');
    try { return frame ? frame.contentDocument : null; } catch (e) { return null; }
  }

  function watchFrame() {
    var frame = byId('training-console-frame');
    if (!frame) { return; }
    frame.addEventListener('load', function () {
      clearSpotlight();
      var doc = frameDoc();
      if (!doc) { return; }
      doc.addEventListener('htmx:afterRequest', poke);
      doc.addEventListener('pointerdown', foldForConsole, true);
      doc.addEventListener('focusin', foldForConsole, true);
    });
  }

  /* Over the frame, the HUD folds to its handle as soon as the operator works in the console, by pointer or by
     keyboard, so nothing it covers stays out of reach; a reward peeks it open, and the handle brings it back. */
  function foldForConsole() {
    var wrap = hudWrap();
    if (wrap && !wrap.hidden && overlayMode() && !collapsed()) { setCollapsed(true, true); }
  }

  /* Showing a tab: the Console tab asks the HUD at once, the Campaign tab fetches a map that changed while away. */
  function watchTabs() {
    var observer = new MutationObserver(function () {
      if (consoleShowing()) { poke(); }
      if (campaignStale && shown(byId('tpanel-campaign'))) { refreshCampaign(); }
    });
    ['tpanel-console', 'tpanel-campaign'].forEach(function (id) {
      var panel = byId(id);
      if (panel) { observer.observe(panel, { attributes: true, attributeFilter: ['style'] }); }
    });
  }

  var spot = null;

  function frameStyles(doc) {
    if (doc.getElementById('mission-frame-css')) { return; }
    var link = doc.createElement('link');
    link.id = 'mission-frame-css';
    link.rel = 'stylesheet';
    link.href = '/static/css/mission.css';
    doc.head.appendChild(link);
  }

  function findInFrame(doc, selector) {
    try { return doc.querySelector(selector); } catch (e) { return null; }
  }

  /* Shown on screen: a box, and not inside a closed <details> or a hidden panel (checkVisibility knows both). */
  function visibleBox(el) {
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) { return false; }
    var closed = el.closest('details:not([open])');
    if (closed && !el.closest('summary')) { return false; }
    return typeof el.checkVisibility === 'function' ? el.checkVisibility() : true;
  }

  /* A control's name as the operator reads it: its text up to any explanatory dash, kept short. */
  function label(el) {
    var text = (el.textContent || '').replace(/\s+/g, ' ').replace(/[\u25b6\u25b8]/g, '').trim();
    return text.split(/ [\u2014-] /)[0].slice(0, 48).trim();
  }

  /* The control that would show *el*: a closed <details>'s summary, or the tab button for a hidden panel. */
  function opener(doc, el) {
    if (el.tagName === 'DETAILS' && !el.open) { return el.querySelector('summary'); }
    if (!el.id) { return null; }
    var tab = doc.querySelector('[data-panel="' + el.id + '"]');
    return tab && visibleBox(tab) ? tab : null;
  }

  /* What to ring: the target when it shows, else the nearest control that would show it, named. */
  function ringTarget(doc, target) {
    if (visibleBox(target)) { return { el: target, open: '' }; }
    for (var el = target.parentElement; el && el !== doc.body; el = el.parentElement) {
      var control = opener(doc, el);
      if (control && visibleBox(control)) { return { el: control, open: label(control) }; }
    }
    return null;
  }

  /* Bring *el* into view inside the frame only: scrollIntoView would scroll the training page as well. */
  function scrollWithinFrame(doc, el) {
    var win = doc.defaultView;
    for (var box = el.parentElement; box; box = box.parentElement) {
      var style = win.getComputedStyle(box);
      if (box.scrollHeight > box.clientHeight && /(auto|scroll)/.test(style.overflowY)) {
        var r = el.getBoundingClientRect();
        var b = box.getBoundingClientRect();
        if (r.top < b.top || r.bottom > b.bottom) { box.scrollTop += r.top - b.top - (b.height - r.height) / 2; }
      }
    }
    var top = el.getBoundingClientRect().top;
    if (top < 0 || top > win.innerHeight) { win.scrollBy(0, top - win.innerHeight / 2); }
  }

  function placeRing() {
    if (!spot) { return; }
    if (spot.doc !== frameDoc() || !spot.doc.contains(spot.target) || !visibleBox(spot.target)) {
      clearSpotlight();
      return;
    }
    var r = spot.target.getBoundingClientRect();
    var pad = 6;
    spot.ring.style.top = (r.top - pad) + 'px';
    spot.ring.style.left = (r.left - pad) + 'px';
    spot.ring.style.width = (r.width + pad * 2) + 'px';
    spot.ring.style.height = (r.height + pad * 2) + 'px';
    spot.raf = requestAnimationFrame(placeRing);
  }

  function escapeClears(event) {
    if (event.key === 'Escape') { clearSpotlight(); }
  }

  function clearSpotlight() {
    if (!spot) { return; }
    cancelAnimationFrame(spot.raf);
    spot.ring.remove();
    spot.doc.removeEventListener('click', clearSpotlight, true);
    spot.doc.removeEventListener('keydown', escapeClears, true);
    document.removeEventListener('keydown', escapeClears, true);
    spot = null;
  }

  /* The HUD over the frame must not hide what the spotlight points at: it folds away to its handle. */
  function clearHudFrom(doc, el) {
    if (!overlayMode() || collapsed()) { return; }
    var wrap = hudWrap();
    var frame = byId('training-console-frame');
    if (!wrap || !frame || wrap.hidden) { return; }
    var edge = wrap.getBoundingClientRect().left - frame.getBoundingClientRect().left;
    var r = el.getBoundingClientRect();
    if (r.left + r.width / 2 > edge) { setCollapsed(true, false); }
  }

  function drawSpotlight(selector) {
    clearSpotlight();
    var doc = frameDoc();
    var target = doc && doc.body ? findInFrame(doc, selector) : null;
    var ring = target ? ringTarget(doc, target) : null;
    if (!ring) {
      announce('That control is not on the console page yet.');
      return 'Not on screen yet';
    }
    frameStyles(doc);
    scrollWithinFrame(doc, ring.el);
    clearHudFrom(doc, ring.el);
    var mark = doc.createElement('div');
    mark.className = 'mission-spotlight';
    mark.setAttribute('aria-hidden', 'true');
    if (ring.open) { mark.dataset.say = 'Open ' + ring.open + ' first'; }
    doc.body.appendChild(mark);
    spot = { doc: doc, target: ring.el, ring: mark, raf: 0 };
    doc.addEventListener('click', clearSpotlight, true);
    doc.addEventListener('keydown', escapeClears, true);
    document.addEventListener('keydown', escapeClears, true);
    placeRing();
    if (!ring.open) { return ''; }
    announce('Open ' + ring.open + ' first.');
    return 'Open ' + ring.open + ' first';
  }

  /* Show me: the ring in the console, and in the HUD a note when the control itself cannot be shown. */
  SPECTRE.action('missionSpotlight', function (btn) {
    showTab('console');
    var li = btn.closest('[data-objective-id]');
    spotlightFor(li ? li.dataset.objectiveId : '', btn.dataset.spotlight);
  });

  /* ── The debrief: the HUD comes down, the stars come out one by one ── */
  function revealStar(slot) {
    slot.classList.add('is-revealed');
    if (slot.classList.contains('is-earned')) { tone(STAR_NOTE); }
  }

  function revealStars(debrief) {
    var slots = Array.prototype.slice.call(debrief.querySelectorAll('.mission-star-slot'));
    var finish = function () { debrief.dataset.reveal = 'done'; };
    if (motionOff()) {
      slots.forEach(function (slot) { slot.classList.add('is-revealed'); });
      finish();
      return;
    }
    slots.forEach(function (slot, i) {
      setTimeout(function () {
        revealStar(slot);
        if (i === slots.length - 1) { finish(); }
      }, STAR_FIRST_MS + i * STAR_GAP_MS);
    });
    if (!slots.length) { finish(); }
  }

  /* ── The chapter's moment: this run earned a star on the last mission of its chapter. The server may say so
     (chapter_complete); otherwise the campaign map, fetched at the start, has the chapter, its order and its stars. ── */
  function chapterTotals(debrief) {
    var node = document.querySelector('.mission-node[data-mission-id="' + CSS.escape(debrief.dataset.missionId) + '"]');
    var chapter = node ? node.closest('.mission-chapter') : null;
    if (!chapter) { return null; }
    var nodes = Array.prototype.slice.call(chapter.querySelectorAll('.mission-node'));
    if (nodes[nodes.length - 1] !== node) { return null; }
    var stars = nodes.reduce(function (sum, n) {
      var own = Number(n.dataset.stars) || 0;
      return sum + (n === node ? Math.max(own, Number(debrief.dataset.stars) || 0) : own);
    }, 0);
    var title = chapter.querySelector('.mission-chapter__title');
    return { title: title ? title.textContent.trim() : '', stars: stars, max: nodes.length * 3 };
  }

  function chapterMoment(debrief) {
    if (byId('mission-chapter-complete') || Number(debrief.dataset.stars) === 0) { return; }
    var totals = chapterTotals(debrief);
    if (!totals) { return; }
    var box = document.createElement('section');
    box.id = 'mission-chapter-complete';
    box.className = 'mission-chapter-done';
    box.setAttribute('aria-label', 'Chapter complete');
    var eyebrow = document.createElement('p');
    eyebrow.className = 'mission-eyebrow';
    eyebrow.textContent = 'Chapter complete';
    var title = document.createElement('h3');
    title.className = 'mission-chapter-done__title';
    title.textContent = totals.title;
    var line = document.createElement('p');
    line.className = 'mission-chapter-done__stars';
    line.textContent = totals.stars + '/' + totals.max + ' stars';
    box.appendChild(eyebrow);
    box.appendChild(title);
    box.appendChild(line);
    var next = byId('mission-next-lock');
    if (next) { box.appendChild(next); }
    var stats = debrief.querySelector('.mission-stats');
    var anchor = byId('mission-rank-points') || stats;
    if (anchor) { anchor.parentNode.insertBefore(box, anchor.nextSibling); }
    announce('Chapter complete: ' + totals.title + '.');
  }

  SPECTRE.init('missionDebrief', function (debrief) {
    stopHud();
    chapterMoment(debrief);
    setStage('debrief');
    showTab('campaign');
    focusHeading(debrief);
    if (Number(debrief.dataset.stars) > 0) { tone(COMPLETE_NOTES); }
    revealStars(debrief);
    var points = byId('mission-debrief-points');
    if (points) { countUp(points, 0, Number(debrief.dataset.points) || 0); }
  });

  /* ── Back to the campaign: the stars earned fly home into the mission's node, stamped when a new best ── */
  function flightPlan(debrief) {
    var id = debrief.dataset.missionId;
    return {
      id: id,
      stars: Number(debrief.dataset.stars) || 0,
      points: Number(debrief.dataset.points) || 0,
      before: bestsAtStart[id] || null,
      next: debrief.dataset.nextMissionId || id,
      from: Array.prototype.map.call(debrief.querySelectorAll('.mission-star-slot.is-earned .mission-star'),
        function (star) { return star.getBoundingClientRect(); })
    };
  }

  function newBest(plan) {
    if (!plan.before || plan.stars === 0) { return false; }
    return plan.stars > plan.before.stars || plan.points > plan.before.points;
  }

  function stamp(node) {
    var mark = document.createElement('span');
    mark.className = 'mission-node__stamp' + (motionOff() ? ' is-still' : '');
    mark.textContent = 'New best';
    node.appendChild(mark);
    announce('New best.');
    setTimeout(function () { mark.remove(); }, STAMP_MS);
  }

  function flyStar(rect, to, i) {
    var star = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    star.setAttribute('viewBox', '0 0 24 24');
    star.setAttribute('aria-hidden', 'true');
    star.setAttribute('class', 'mission-star is-earned mission-flying-star');
    var shape = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    shape.setAttribute('points', '12,1.8 15.1,8.4 22.2,9.2 16.9,14.1 18.3,21.2 12,17.6 5.7,21.2 7.1,14.1 1.8,9.2 8.9,8.4');
    star.appendChild(shape);
    star.style.left = rect.left + 'px';
    star.style.top = rect.top + 'px';
    star.style.width = rect.width + 'px';
    star.style.height = rect.height + 'px';
    star.style.transitionDelay = (i * 120) + 'ms';
    document.body.appendChild(star);
    star.getBoundingClientRect();   /* commit the start before the move */
    var scale = to.height / rect.height;
    star.style.transform = 'translate(' + (to.left + i * to.height - rect.left) + 'px,' + (to.top - rect.top) + 'px) scale(' + scale + ')';
    setTimeout(function () { star.remove(); }, FLIGHT_MS + i * 120 + 100);
  }

  function landFlight(plan) {
    var node = document.querySelector('.mission-node[data-mission-id="' + plan.id + '"]');
    if (!node) { return; }
    var main = byId('training-main');
    var row = node.querySelector('.mission-stars') || node;
    if (main) {
      var r = node.getBoundingClientRect();
      var m = main.getBoundingClientRect();
      if (r.top < m.top || r.bottom > m.bottom) { main.scrollTop += r.top - m.top - m.height / 3; }
    }
    if (!motionOff()) {
      var to = row.getBoundingClientRect();
      plan.from.forEach(function (rect, i) { flyStar(rect, to, i); });
    }
    if (newBest(plan)) { setTimeout(function () { stamp(node); }, motionOff() ? 0 : FLIGHT_MS); }
    focusNode(plan.next);
  }

  SPECTRE.action('missionToCampaign', function () {
    var debrief = byId('mission-debrief');
    var plan = debrief ? flightPlan(debrief) : null;
    clearStage();
    if (campaignStale) { refreshCampaign(); }   /* now, so the flight waits for the map it lands on */
    showTab('campaign');
    if (!plan) { return; }
    var region = byId('mission-campaign');
    if (region && region.classList.contains('htmx-request')) {
      region.addEventListener('htmx:afterSettle', function once() {
        region.removeEventListener('htmx:afterSettle', once);
        landFlight(plan);
      });
    } else {
      requestAnimationFrame(function () { landFlight(plan); });
    }
  });

  /* ── On load: the sound toggle's state, the frame and tabs watched, a mission still running after a reload ── */
  document.addEventListener('DOMContentLoaded', function () {
    showSoundState();
    watchFrame();
    watchTabs();
    var info = running();
    if (info && byId('mission-hud-dock')) { startHud(info, 'restore'); }
  });
}());
