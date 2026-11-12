/* SPECTRE first-party script: the intercept engine's fragments (SPC-199).
 *
 * Moved from the inline blocks in partials/all_intercepts_result.html, intercept_result.html and
 * intercept_geometry.html, and the handlers on their rows, headers and buttons. The all-intercepts sort state used
 * to be a variable the fragment declared afresh on every swap; it is now held on the table it sorts. The geometry
 * panel's id prefix and opener come from its own data-id-prefix and data-opener, and its chart data from a JSON
 * block, where they used to be written into the script by Jinja.
 */

/* ── Toggle detail row ── */
function aiToggle(idx) {
  var det  = document.getElementById('ai-detail-' + idx);
  var chev = document.getElementById('ai-chevron-' + idx);
  if (!det) return;
  var open = det.style.display !== 'none';
  det.style.display = open ? 'none' : '';
  if (chev) chev.innerHTML = open ? '&#9654;' : '&#9660;';
  /* Same fact as the chevron, for an operator who cannot see it. */
  var row = document.querySelector('[aria-controls="ai-detail-' + idx + '"]');
  if (row) row.setAttribute('aria-expanded', open ? 'false' : 'true');
}

/* ── Pre-fill the intercept engine ── */
function aiLoadEngine(redSat, blueSat, epoch) {
  if (typeof SPECTRE.switchToEngine === 'function') SPECTRE.switchToEngine();
  var redSel  = document.getElementById('ie-red-sat');
  var blueSel = document.getElementById('ie-blue-sat');
  var startIn = document.querySelector('input[name="manoeuvre_start"]');
  if (redSel)  redSel.value  = redSat;
  if (blueSel) blueSel.value = blueSat;
  if (startIn) startIn.value = epoch;
  var engine = document.getElementById('intercept-engine-form');
  if (engine) engine.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* ── Column sort: the state is held on the table, so a new result starts unsorted ── */

function aiSort(col, type) {
  var table = document.getElementById('all-intercepts-table');
  if (!table) return;
  var tbody = table.tBodies[0];
  var sort = table.spectreSort || (table.spectreSort = { col: -1, asc: true });

  /* Toggle direction if same column, else reset to ascending */
  if (sort.col === col) { sort.asc = !sort.asc; }
  else { sort.col = col; sort.asc = true; }

  _aiMarkSortHeader(table, col, sort.asc);
  var grouped = _aiPairRows(Array.from(tbody.rows));
  grouped.pairs.sort(_aiCompare(col, type, sort.asc));

  /* Re-insert: sorted pairs first, failed rows last */
  grouped.pairs.forEach(function(pair) {
    tbody.appendChild(pair[0]);
    if (pair[1]) tbody.appendChild(pair[1]);
  });
  grouped.orphans.forEach(function(r) { tbody.appendChild(r); });
}

/* Sort indicators in the header. The glyph and aria-sort are the same fact
   for two different operators, so they are written together and can never
   drift apart. */
function _aiMarkSortHeader(table, col, asc) {
  table.querySelectorAll('thead .hrr-sort-ind').forEach(function(s) { s.textContent = ''; });
  table.querySelectorAll('thead th[aria-sort]').forEach(function(h) { h.setAttribute('aria-sort', 'none'); });
  var th = table.querySelectorAll('thead th')[col];
  if (!th) return;
  var ind = th.querySelector('.hrr-sort-ind');
  if (ind) ind.textContent = asc ? ' ▲' : ' ▼';
  th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
}

/* Parent rows paired with the detail row that follows each; rows that are
   neither (failed methods) are kept apart to go last. */
function _aiPairRows(rows) {
  var pairs = [];
  var orphans = [];
  var i = 0;
  while (i < rows.length) {
    var row = rows[i];
    if (!row.classList.contains('threat-parent')) {
      orphans.push(row);
      i++;
      continue;
    }
    var next = rows[i + 1];
    var detail = (next && !next.classList.contains('threat-parent')) ? next : null;
    pairs.push([row, detail]);
    i += detail ? 2 : 1;
  }
  return { pairs: pairs, orphans: orphans };
}

/* Orders pairs by the parent row's data-sort-<col>; a numeric column reads an
   unparseable value as Infinity, so it sorts last ascending. */
function _aiSortKey(row, col, type) {
  var v = row.getAttribute('data-sort-' + col) || '';
  if (type !== 'num') return v;
  var n = Number.parseFloat(v);
  return Number.isNaN(n) ? Infinity : n;
}

function _aiCompare(col, type, asc) {
  return function(a, b) {
    var av = _aiSortKey(a[0], col, type);
    var bv = _aiSortKey(b[0], col, type);
    if (av < bv) return asc ? -1 : 1;
    if (av > bv) return asc ?  1 : -1;
    return 0;
  };
}

SPECTRE.action('aiToggle', function (el) { aiToggle(Number(el.dataset.idx)); });
SPECTRE.action('aiSort', function (el) { aiSort(Number(el.dataset.col), el.dataset.kind); });
/* The Load button sits in a clickable row: a click runs the innermost action only, and its Enter reaches the
   button, not the row, because only an element carrying data-activate answers to the row's keys. */
SPECTRE.action('aiLoadEngine', function (el) { aiLoadEngine(el.dataset.red, el.dataset.blue, el.dataset.epoch); });

/* ── Intercept result: copy the summary ── */
SPECTRE.action('copyClip', function (btn) {
  navigator.clipboard.writeText(btn.dataset.clip).then(function () {
    var orig = btn.textContent;
    btn.textContent = '\u2713 Copied';
    setTimeout(function () { btn.textContent = orig; }, 1600);
  });
});

/* ── Orbital events: an event's epoch becomes the manoeuvre start ── */
SPECTRE.action('setManoeuvreStart', function (el) {
  document.querySelector('#intercept-engine-form [name=manoeuvre_start]').value = el.dataset.epoch;
});

/* ── Relative geometry panel: charts and view tabs ── */
function geometryCharts(panel) {
  /* Every id in this panel carries the route's prefix, so a second panel on the page finds only its own nodes. */
  var IDS = panel.dataset.idPrefix;
  /* ── Parse server-rendered chart data (safe — no user strings in data): a JSON string, read from its data block ── */
  var block = document.getElementById(IDS + 'cw-data');
  if (!block) { return; }
  var _cwd = JSON.parse(JSON.parse(block.textContent));

  /* ── Dark-theme Chart.js defaults ── */
  var GRID  = 'rgba(255,255,255,0.07)';
  var TICK  = '#6b7280';
  var RED   = '#ef4444';
  var BLUE  = '#3b8beb';
  var GREEN = '#22c55e';
  var GREY  = '#6b7280';
  var GOLD  = '#f59e0b';

  function _baseScaleOpts(xlabel, ylabel) {
    return {
      x: { title: { display: true, text: xlabel, color: TICK, font: { size: 11 } },
           grid: { color: GRID }, ticks: { color: TICK, font: { size: 10 } } },
      y: { title: { display: true, text: ylabel, color: TICK, font: { size: 11 } },
           grid: { color: GRID }, ticks: { color: TICK, font: { size: 10 } } },
    };
  }

  function _pointStyle(label, color, radius) {
    return { label: label, data: [{x: _cwd.target.vbar, y: _cwd.target.rbar}],
             type: 'scatter', pointRadius: radius, pointBackgroundColor: color,
             pointBorderColor: color, showLine: false };
  }

  /* ── Build datasets for V-bar / R-bar (plan view) ── */
  function _makeVRDatasets() {
    var sets = [];
    if (_cwd.vr_coast && _cwd.vr_coast.length > 1) {
      sets.push({ label: 'Pre-burn coast', data: _cwd.vr_coast.map(function(p){return{x:p[0],y:p[1]};}),
                  borderColor: GREY, backgroundColor: 'transparent', borderWidth: 1.5,
                  borderDash: [4,3], pointRadius: 0, tension: 0.3 });
    }
    sets.push({ label: 'Transfer trajectory', data: _cwd.vr_transfer.map(function(p){return{x:p[0],y:p[1]};}),
                borderColor: RED, backgroundColor: 'rgba(239,68,68,0.08)', borderWidth: 2,
                pointRadius: 0, tension: 0.3, fill: false });
    /* Initial position */
    if (_cwd.vr_transfer.length > 0) {
      var p0 = _cwd.vr_transfer[0];
      sets.push({ label: 'Burn point', data: [{x: p0[0], y: p0[1]}],
                  type: 'scatter', pointRadius: 7, pointStyle: 'rectRot',
                  pointBackgroundColor: RED, pointBorderColor: RED, showLine: false });
    }
    var startSrc = (_cwd.vr_coast && _cwd.vr_coast.length > 0) ? _cwd.vr_coast : _cwd.vr_transfer;
    if (startSrc && startSrc.length > 0) {
      var sp = startSrc[0];
      sets.push({ label: 'Initial position', data: [{x: sp[0], y: sp[1]}],
                  type: 'scatter', pointRadius: 7, pointStyle: 'circle',
                  pointBackgroundColor: BLUE, pointBorderColor: BLUE, showLine: false });
    }
    /* Target at origin */
    sets.push({ label: 'Target', data: [{x: 0, y: 0}],
                type: 'scatter', pointRadius: 9, pointStyle: 'star',
                pointBackgroundColor: GREEN, pointBorderColor: GREEN, showLine: false });
    /* Approach corridor: dashed lines at ±0.1 km R-bar near approach */
    return sets;
  }

  /* ── Build datasets for H-bar / R-bar (out-of-plane view) ── */
  function _makeHRDatasets() {
    var sets = [];
    if (_cwd.hr_coast && _cwd.hr_coast.length > 1) {
      sets.push({ label: 'Pre-burn coast', data: _cwd.hr_coast.map(function(p){return{x:p[0],y:p[1]};}),
                  borderColor: GREY, backgroundColor: 'transparent', borderWidth: 1.5,
                  borderDash: [4,3], pointRadius: 0, tension: 0.3 });
    }
    sets.push({ label: 'Transfer trajectory', data: _cwd.hr_transfer.map(function(p){return{x:p[0],y:p[1]};}),
                borderColor: GOLD, backgroundColor: 'rgba(245,158,11,0.08)', borderWidth: 2,
                pointRadius: 0, tension: 0.3, fill: false });
    if (_cwd.hr_transfer.length > 0) {
      var p0h = _cwd.hr_transfer[0];
      sets.push({ label: 'Burn point', data: [{x: p0h[0], y: p0h[1]}],
                  type: 'scatter', pointRadius: 7, pointStyle: 'rectRot',
                  pointBackgroundColor: GOLD, pointBorderColor: GOLD, showLine: false });
    }
    sets.push({ label: 'Target', data: [{x: 0, y: 0}],
                type: 'scatter', pointRadius: 9, pointStyle: 'star',
                pointBackgroundColor: GREEN, pointBorderColor: GREEN, showLine: false });
    return sets;
  }

  /* ── Build datasets for Range vs Time ── */
  function _makeRTDatasets() {
    var pts = _cwd.range_series.map(function(p){return{x: p[0]/60.0, y: p[1]};});
    return [{
      label: 'Range km', data: pts,
      borderColor: BLUE, backgroundColor: 'rgba(59,139,235,0.10)',
      borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
    }];
  }

  /* ── Common chart options ── */
  function _chartOpts(title, xLabel, yLabel) {
    return {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: { display: true, position: 'bottom',
                  labels: { color: TICK, font: { size: 10 }, boxWidth: 14, padding: 10 } },
        title: { display: !!title, text: title, color: '#e5e7eb', font: { size: 12, weight: '700' } },
        tooltip: {
          backgroundColor: '#1f2937', titleColor: '#f9fafb', bodyColor: TICK,
          borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
          callbacks: {
            label: function(ctx) {
              var v = ctx.parsed;
              if (v.y !== undefined && v.x !== undefined) {
                return ctx.dataset.label + ': (' + v.x.toFixed(3) + ', ' + v.y.toFixed(3) + ') km';
              }
              return ctx.dataset.label + ': ' + (v.y !== undefined ? v.y : ctx.parsed).toFixed(3);
            }
          }
        }
      },
      scales: _baseScaleOpts(xLabel, yLabel),
    };
  }

  /* ── Instantiate charts ── */
  var _charts = {};

  function _initVR() {
    if (_charts.vr) return;
    var ctx = document.getElementById(IDS + 'cw-chart-vr');
    if (!ctx) return;
    _charts.vr = new Chart(ctx, {
      type: 'line',
      data: { datasets: _makeVRDatasets() },
      options: _chartOpts(null, 'V-bar (Along-track) km', 'R-bar (Radial) km'),
    });
    /* Add zero-axis reference lines after render */
    _charts.vr.options.scales.x.grid.drawOnChartArea = true;
    _charts.vr.options.scales.y.grid.drawOnChartArea = true;
  }

  function _initHR() {
    if (_charts.hr) return;
    var ctx = document.getElementById(IDS + 'cw-chart-hr');
    if (!ctx) return;
    _charts.hr = new Chart(ctx, {
      type: 'line',
      data: { datasets: _makeHRDatasets() },
      options: _chartOpts(null, 'H-bar (Cross-track) km', 'R-bar (Radial) km'),
    });
  }

  function _initRT() {
    if (_charts.rt) return;
    var ctx = document.getElementById(IDS + 'cw-chart-rt');
    if (!ctx) return;
    _charts.rt = new Chart(ctx, {
      type: 'line',
      data: { datasets: _makeRTDatasets() },
      options: _chartOpts(null, 'Time (minutes)', 'Range km'),
    });
  }

  /* ── Tab switching: bound to this panel's own buttons, not a global the next panel would replace ── */
  function geomTab(id) {
    ['vr','hr','rt'].forEach(function(tid) {
      var panel = document.getElementById(IDS + 'gchart-' + tid);
      var btn   = document.getElementById(IDS + 'gtab-' + tid);
      if (!panel || !btn) return;
      var active = (tid === id);
      panel.style.display = active ? '' : 'none';
      btn.style.background = active ? 'rgba(59,139,235,0.18)' : 'transparent';
      btn.style.color      = active ? 'var(--ops-blue)' : 'var(--text-dim)';
      btn.style.borderColor = active ? 'rgba(59,139,235,0.4)' : 'var(--border)';
    });
    if (id === 'vr') _initVR();
    if (id === 'hr') { _initHR(); }
    if (id === 'rt') { _initRT(); }
  }
  ['vr','hr','rt'].forEach(function(tid) {
    var btn = document.getElementById(IDS + 'gtab-' + tid);
    if (btn) { btn.addEventListener('click', function () { geomTab(tid); }); }
  });

  /* Init first tab immediately */
  _initVR();

}

/* ── Relative geometry panel: Escape, close and focus ── */
/* Escape closes the geometry panel. The close control is the only other way
   out and it is a single glyph in a corner, which is a mouse-shaped exit on a
   keyboard-reachable panel.

   The listener is on the PANEL, not on document. On document it fired for
   every Escape anywhere on the console: the one that dismisses a browser
   autocomplete in the threat sweep search box destroyed a geometry panel
   sitting in another hero tab, and the operator found it gone on returning.
   Scoped to the panel subtree, keydown still reaches it from every control
   inside the panel, because keydown bubbles, and from nowhere else. The
   listener also dies with the node, so there is no global to replace on the
   next swap and nothing left behind when htmx removes the panel.

   For that scoping to be usable, focus has to be inside the panel to begin
   with, which is the other half of this block: the heading takes focus on
   open, and the control that opened the panel takes it back on close.

   Every id carries the route's prefix and nothing is put on window, so the
   intercept panel and a Decision Engine view open on the same page each find,
   close and return focus for their own panel only. */
function geometryExit(panel) {
  var IDS = panel.dataset.idPrefix;
  var OPENER = panel.dataset.opener;

  /* The control that opened this panel: the intercept result's button, or
     the Decision Engine cell whose form was submitted. Falls back to
     whatever had focus when the fragment landed, which is that same button
     on the keyboard path. */
  var opener = document.querySelector(OPENER);
  if (!opener) {
    var active = document.activeElement;
    if (active && active !== document.body && typeof active.focus === 'function') {
      opener = active;
    }
  }

  function spectreCloseGeometryPanel() {
    var p = document.getElementById(IDS + 'geom-panel');
    if (p) { p.remove(); }
    /* Without this, focus falls to body and the keyboard operator restarts
       from the top of the console at the moment the exit was meant to help. */
    if (opener && document.contains(opener)) { opener.focus(); }
  }

  panel.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') { return; }
    event.stopPropagation();
    spectreCloseGeometryPanel();
  });

  var close = panel.querySelector('.geom-close');
  if (close) { close.addEventListener('click', spectreCloseGeometryPanel); }

  var heading = document.getElementById(IDS + 'geom-panel-heading');
  if (heading) { heading.focus(); }
}

SPECTRE.init('geometry', function (panel) {
  geometryCharts(panel);
  geometryExit(panel);
});
