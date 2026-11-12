/* SPECTRE first-party script: the operator console shell (SPC-199).
 *
 * Moved from the inline blocks at the foot of templates/operator.html, the UDL status, element-set refresh and
 * splash fragments, and the handlers on their controls, so the policy needs no 'unsafe-inline'. The behaviour is
 * the inline code's; where it changed, the comment says why.
 */
/* ── Orbital events fetcher ─────────────────────────────────────────────── */
function fetchOrbitalEvents() {
  var redSel = document.getElementById('ie-red-sat');
  var blueSel = document.getElementById('ie-blue-sat');
  var redSat = redSel ? redSel.value : '';
  var blueSat = blueSel ? blueSel.value : '';
  if (!redSat && !blueSat) {
    document.getElementById('orbital-events').innerHTML =
      '<p class="error-msg">Select at least one satellite first.</p>';
    return;
  }
  var btn = document.getElementById('ie-events-btn');
  btn.disabled = true;
  btn.textContent = 'Loading\u2026';
  var params = new URLSearchParams();
  if (redSat) params.set('red_sat', redSat);
  if (blueSat) params.set('blue_sat', blueSat);
  fetch('/plan/maneuver/orbital-events?' + params.toString())
    .then(function(resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.text();
    })
    .then(function(html) {
      document.getElementById('orbital-events').innerHTML = html;
    })
    .catch(function(err) {
      /* textContent, not innerHTML: an Error message is not ours to trust as
         markup, and nothing here needs it to be markup. */
      var box = document.getElementById('orbital-events');
      box.replaceChildren();
      var p = document.createElement('p');
      p.className = 'error-msg';
      p.textContent = 'Query failed: ' + err.message;
      box.appendChild(p);
    })
    .finally(function() {
      btn.disabled = false;
      btn.textContent = 'Events';
    });
}
SPECTRE.action('fetchOrbitalEvents', function () { fetchOrbitalEvents(); });

/* ── Tab switching controllers ──────────────────────────────────────────── */
/* Sidebar tabs */
function sbTab(btn) {
  var tabs = document.querySelectorAll('.stab');
  var panels = document.querySelectorAll('.sidebar-panel');
  var target = btn.dataset.panel;
  tabs.forEach(function(t) { t.classList.remove('active'); });
  panels.forEach(function(p) { p.classList.remove('active'); });
  btn.classList.add('active');
  var panel = document.getElementById(target);
  if (panel) panel.classList.add('active');
}

/* Asset inner sub-tabs */
function assetTab(btn) {
  var tabs = document.querySelectorAll('.atab');
  var panels = document.querySelectorAll('.asset-panel');
  var target = btn.dataset.panel;
  tabs.forEach(function(t) { t.classList.remove('active'); });
  panels.forEach(function(p) { p.classList.remove('active'); });
  btn.classList.add('active');
  var panel = document.getElementById(target);
  if (panel) panel.classList.add('active');
}

/* Hero tabs */
function heroTab(btn) {
  var tabs = document.querySelectorAll('.htab');
  var panels = document.querySelectorAll('.hero-panel');
  var target = btn.dataset.panel;
  tabs.forEach(function(t) { t.classList.remove('active'); });
  panels.forEach(function(p) { p.classList.remove('active'); });
  btn.classList.add('active');
  var panel = document.getElementById(target);
  if (panel) {
    panel.classList.add('active');
    /* Lazy-load panels declared with hx-get (loads once on first reveal) */
    if (panel.getAttribute('hx-get') && !panel.dataset.htmxLoaded) {
      panel.dataset.htmxLoaded = '1';
      htmx.process(panel);
      htmx.trigger(panel, 'load');
    }
    /* When switching to Threat Sweep, refresh target-config with current red_sat */
    if (target === 'hero-sweep') {
      var sel = document.getElementById('ts-red-sat');
      var val = sel ? (sel.value || '') : '';
      var url = '/plan/threat/target-config' + (val ? '?red_sat=' + encodeURIComponent(val) : '');
      htmx.ajax('GET', url, {target: '#ts-target-config', swap: 'innerHTML'});
    }
  }
}

/* Engine sub-tabs (Calculator / Trade-Space / History) */
function engineTab(btn) {
  var tabs = document.querySelectorAll('.etab');
  var panels = document.querySelectorAll('.engine-tab-panel');
  var target = btn.dataset.panel;
  tabs.forEach(function(t) { t.classList.remove('active'); });
  panels.forEach(function(p) { p.classList.remove('active'); });
  btn.classList.add('active');
  var panel = document.getElementById(target);
  if (panel) panel.classList.add('active');
  if (target === 'et-trade' && window._tsChartInstance) {
    setTimeout(function() { window._tsChartInstance.resize(); }, 50);
  }
}

/* Sidebar collapse — must clear inline style set by drag-resize */
var _sidebarSavedWidth = null;
function toggleSidebar() {
  var layout = document.querySelector('.console-layout');
  var btn = document.getElementById('sidebar-collapse-btn');
  if (!layout) return;
  if (!layout.classList.contains('sidebar-collapsed')) {
    /* Collapsing: save any inline width then remove it so the class rule wins */
    _sidebarSavedWidth = layout.style.gridTemplateColumns || null;
    layout.style.gridTemplateColumns = '';
    layout.classList.add('sidebar-collapsed');
    btn.innerHTML = '&#9654;';
    btn.title = 'Expand sidebar';
  } else {
    /* Expanding: restore inline width if there was one */
    layout.classList.remove('sidebar-collapsed');
    if (_sidebarSavedWidth) {
      layout.style.gridTemplateColumns = _sidebarSavedWidth;
    }
    btn.innerHTML = '&#9664;';
    btn.title = 'Collapse sidebar';
  }
  if (window._tsChartInstance) {
    setTimeout(function() { window._tsChartInstance.resize(); }, 300);
  }
}

/* Switch to Intercept Engine hero tab programmatically */
function switchToEngine() {
  var btn = document.querySelector('.htab[data-panel="hero-engine"]');
  if (btn) heroTab(btn);
  var panel = document.getElementById('hero-engine');
  if (panel) {
    panel.classList.add('engine-flash');
    setTimeout(function() { panel.classList.remove('engine-flash'); }, 1300);
  }
}

/* Show the Decision Engine once a scenario opened from the sweep has been swapped into it (SPC-150) */
function openDecisionPanel() {
  var btn = document.querySelector('.htab[data-panel="hero-decision"]');
  if (btn) heroTab(btn);
  var panel = document.getElementById('hero-decision');
  if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
/* One delegated listener for every control marked data-opens-decision, so none carries an hx-on handler, which
   htmx compiles with new Function and the policy refuses (app.py) */
document.body.addEventListener('htmx:afterRequest', function (e) {
  var elt = e.detail && e.detail.elt;
  if (e.detail.successful && elt && elt.dataset && elt.dataset.opensDecision !== undefined) openDecisionPanel();
});

/* Switch to Trade-Space engine sub-tab programmatically */
function switchToTradeSpace() {
  switchToEngine();
  var btn = document.querySelector('.etab[data-panel="et-trade"]');
  if (btn) engineTab(btn);
}
SPECTRE.action('sbTab', sbTab);
SPECTRE.action('assetTab', assetTab);
SPECTRE.action('heroTab', heroTab);
SPECTRE.action('engineTab', engineTab);
SPECTRE.action('toggleSidebar', function () { toggleSidebar(); });
/* The sweep's and the intercept table's Load controls switch here (sweep.js, intercepts.js). */
SPECTRE.switchToEngine = switchToEngine;

/* ── Auto-fetch red orbit info when ts-red-sat changes ──────────────────── */
(function() {
  var _lastRedSat = '';

  /* Called by the element set refresh note once UDL has replaced held sets,
     so the card shows the new epoch rather than the one it was drawn with. */
  window.spectreRereadRedCard = function() {
    _lastRedSat = '';
    document.body.dispatchEvent(new Event('htmx:afterSettle'));
  };

  document.body.addEventListener('htmx:afterSettle', function() {
    var sel = document.getElementById('ts-red-sat');
    if (!sel) return;
    var val = sel.value || '';
    if (val && val !== _lastRedSat) {
      _lastRedSat = val;
      htmx.ajax('GET', '/plan/threat/red-orbit-info?red_sat=' + encodeURIComponent(val),
                {target: '#ts-red-orbit-info', swap: 'innerHTML'});
    } else if (!val && _lastRedSat) {
      _lastRedSat = '';
      var tgt = document.getElementById('ts-red-orbit-info');
      if (tgt) tgt.innerHTML = '';
    }
  });
})();

/* ── Sweep target config helpers ────────────────────────────────────────── */
/* Refresh target-config after UDL login, HRR fetch, or any OOB swap that may
   have changed the red satellite list (asset add/remove).  Uses the current
   value of #ts-red-sat so the config always reflects the active selection. */
(function() {
  var _lastConfigSat = '';

  function _refreshTargetConfig() {
    var sel = document.getElementById('ts-red-sat');
    var val = sel ? (sel.value || '') : '';
    if (val === _lastConfigSat) return;           /* no change — skip */
    _lastConfigSat = val;
    var url = '/plan/threat/target-config' + (val ? '?red_sat=' + encodeURIComponent(val) : '');
    htmx.ajax('GET', url, {target: '#ts-target-config', swap: 'innerHTML'});
  }

  document.body.addEventListener('htmx:afterSettle', function(e) {
    /* detail is absent on the plain Event spectreRereadRedCard raises, so it is read with a guard: unguarded it
       threw an uncaught TypeError on every element-set refresh that updated a set. */
    var id = ((e.detail && e.detail.target) || {}).id || '';
    /* Always re-check after events that could change the select list or session state */
    if (id === 'udl-status' || id === 'blue-hrr-list' ||
        id === 'blue-list'  || id === 'red-list') {
      _refreshTargetConfig();
    }
  });

  /* Also fire on direct user selection (hx-trigger="change" on #ts-red-sat
     handles the HTMX update, but we track _lastConfigSat here too). */
  document.body.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'ts-red-sat') {
      _lastConfigSat = '';   /* reset so next afterSettle re-evaluates */
    }
  });
})();

/* ── Sidebar resize controller ──────────────────────────────────────────── */
(function() {
  var handle = document.getElementById('sidebar-resize');
  var layout = document.querySelector('.console-layout');
  if (!handle || !layout) return;

  var startX, startW;

  handle.addEventListener('mousedown', function(e) {
    if (layout.classList.contains('sidebar-collapsed')) return;
    e.preventDefault();
    startX = e.clientX;
    startW = Number.parseInt(getComputedStyle(layout).gridTemplateColumns) || 500;
    handle.classList.add('dragging');
    layout.classList.add('resizing');
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  function onMove(e) {
    var newW = Math.max(280, Math.min(700, startW + (e.clientX - startX)));
    layout.style.gridTemplateColumns = newW + 'px 1fr';
  }

  function onUp() {
    handle.classList.remove('dragging');
    layout.classList.remove('resizing');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    /* Resize chart if visible */
    if (window._tsChartInstance) {
      setTimeout(function() { window._tsChartInstance.resize(); }, 50);
    }
  }
})();

/* ── Trade-Space chart controller ───────────────────────────────────────── */
(function() {
  var _tsChartInstance = null;
  window._tsChartInstance = null;
  var _tsVisible = false;

  var METHOD_COLOURS = {
    'lambert':'#00659E','proximity':'#00659E','hohmann':'#C8A415',
    'rendezvous':'#C8A415','bielliptic':'#27AE60','phasing':'#E67E22',
    'rbar_hop':'#8E44AD','vbar_hop':'#6C3483','hbar_hop':'#4A235A',
    'cw_drift':'#9B59B6','plane_change':'#2ECC71',
    'j2_drift':'#1ABC9C','cola':'#E74C3C','evasion':'#C0392B',
    'geo_drift':'#F39C12','nmc':'#16A085','manoeuvre_detect':'#7F8C8D',
    'detectability':'#95A5A6','fingerprint':'#BDC3C7','terrain':'#D35400',
    'intent_predict':'#E84393','intercept_envelope':'#6C5CE7',
    'stability':'#00CEC9','formation':'#FD79A8','min_time':'#FDCB6E'
  };

  function fmtTime(min) {
    if (min < 60)   return min.toFixed(1) + ' min';
    if (min < 1440) return (min / 60).toFixed(1) + ' hr';
    return (min / 1440).toFixed(1) + ' days';
  }

  /** Called from intercept_result partial after each new solve. */
  window._spectreRenderTradeSpace = function() {
    var btn = document.getElementById('ts-chart-btn');
    var status = document.getElementById('ts-chart-status');
    var clearBtn = document.getElementById('ts-chart-clear');
    var badge = document.getElementById('ts-badge');
    if (!btn) return;

    /* Set button to loading state */
    btn.disabled = true;
    btn.textContent = 'Rendering\u2026';
    if (status) status.textContent = 'Loading chart data\u2026';

    fetch('/plan/maneuver/trade-space-data')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        data = data.filter(function(pt) { return pt.transfer_time_min > 0 && pt.delta_v > 0; });
        if (!data.length) {
          btn.disabled = true;
          btn.textContent = 'View Chart';
          if (status) status.textContent = 'No plottable data (need positive \u0394V and transfer time)';
          if (badge) badge.textContent = '';
          return;
        }

        /* Build datasets */
        var datasets = {};
        data.forEach(function(pt) {
          var key = pt.method;
          if (!datasets[key]) {
            datasets[key] = {
              label: key.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }),
              backgroundColor: METHOD_COLOURS[key] || '#999',
              borderColor: METHOD_COLOURS[key] || '#999',
              pointRadius: 7, pointHoverRadius: 10, data: []
            };
          }
          datasets[key].data.push({ x: pt.transfer_time_min, y: pt.delta_v, label: pt.label, miss: pt.miss_km, score: pt.score });
        });

        var allX = data.map(function(p) { return p.transfer_time_min; });
        var allY = data.map(function(p) { return p.delta_v; });
        var xSpread = Math.max.apply(null, allX) / Math.min.apply(null, allX);
        var ySpread = Math.max.apply(null, allY) / Math.min.apply(null, allY);
        var useLogX = allX.length > 1 && xSpread > 50;
        var useLogY = allY.length > 1 && ySpread > 50;

        /* Render into the canvas */
        var canvas = document.getElementById('tradeSpaceChart');
        if (!canvas || typeof Chart === 'undefined') {
          btn.disabled = true;
          btn.textContent = 'View Chart';
          if (status) status.textContent = 'Chart library not loaded';
          return;
        }

        if (_tsChartInstance) { _tsChartInstance.destroy(); _tsChartInstance = null; }

        _tsChartInstance = new Chart(canvas, {
          type: 'scatter',
          data: { datasets: Object.values(datasets) },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
              legend: { labels: { color: '#D0D8E8', font: { family: 'Segoe UI', size: 11 } } },
              tooltip: {
                callbacks: {
                  label: function(ctx) {
                    var pt = ctx.raw;
                    return [pt.label, '\u0394V: ' + pt.y.toFixed(1) + ' m/s',
                            'Transfer: ' + fmtTime(pt.x),
                            pt.score !== undefined ? 'Score: ' + pt.score + '/100' : 'Miss: ' + pt.miss.toFixed(1) + ' km'];
                  }
                },
                backgroundColor: '#001529', titleColor: '#C8A415',
                bodyColor: '#D0D8E8', borderColor: '#0A3355', borderWidth: 1
              }
            },
            scales: {
              x: {
                type: useLogX ? 'logarithmic' : 'linear',
                title: { display: true, text: 'Transfer Time', color: '#5A7A9A', font: { size: 11 } },
                ticks: { color: '#5A7A9A', callback: function(v) { return fmtTime(v); } },
                grid: { color: 'rgba(10,51,85,0.4)' }
              },
              y: {
                type: useLogY ? 'logarithmic' : 'linear',
                title: { display: true, text: '\u0394V (m/s)', color: '#5A7A9A', font: { size: 11 } },
                ticks: { color: '#5A7A9A' },
                grid: { color: 'rgba(10,51,85,0.4)' }
              }
            }
          }
        });
        window._tsChartInstance = _tsChartInstance;

        /* Chart ready — activate button, update badge, auto-switch to Trade-Space tab */
        btn.disabled = false;
        btn.textContent = _tsVisible ? 'Hide Chart' : 'View Chart (' + data.length + ' pts)';
        if (status) status.textContent = data.length + ' solutions plotted';
        if (badge) badge.textContent = '(' + data.length + ' pts)';
        if (clearBtn) clearBtn.style.display = '';
        switchToTradeSpace();
      })
      .catch(function(err) {
        btn.disabled = true;
        btn.textContent = 'View Chart';
        if (status) status.textContent = 'Chart render failed: ' + err.message;
      });
  };

  /** Toggle chart panel visibility. */
  window._spectreToggleTradeSpace = function() {
    var wrap = document.getElementById('trade-space-canvas-wrap');
    var btn = document.getElementById('ts-chart-btn');
    if (!wrap) return;
    _tsVisible = !_tsVisible;
    wrap.style.display = _tsVisible ? '' : 'none';
    if (btn) btn.textContent = _tsVisible ? 'Hide Chart' : 'View Chart';
    if (_tsVisible && _tsChartInstance) _tsChartInstance.resize();
  };

  /** Reset after history clear. */
  window._spectreResetTradeSpace = function() {
    var wrap = document.getElementById('trade-space-canvas-wrap');
    var btn = document.getElementById('ts-chart-btn');
    var status = document.getElementById('ts-chart-status');
    var clearBtn = document.getElementById('ts-chart-clear');
    var badge = document.getElementById('ts-badge');
    if (_tsChartInstance) { _tsChartInstance.destroy(); _tsChartInstance = null; }
    window._tsChartInstance = null;
    _tsVisible = false;
    if (wrap) wrap.style.display = 'none';
    if (btn) { btn.disabled = true; btn.textContent = 'View Chart'; }
    if (status) status.textContent = 'Run 2+ intercepts to enable';
    if (badge) badge.textContent = '';
    if (clearBtn) clearBtn.style.display = 'none';
  };
})();
SPECTRE.action('toggleTradeSpace', function () { window._spectreToggleTradeSpace(); });
SPECTRE.action('resetTradeSpace', function () { window._spectreResetTradeSpace(); });
/* The intercept results ask for the chart after a run once two or more are held (intercepts.js). */
SPECTRE.init('trade-space-render', function () { window._spectreRenderTradeSpace(); });

/* ── HRR search controller ──────────────────────────────────────────────── */
(function() {
  /**
   * Gather every row from both blue and red HRR tables into a flat array.
   * Each entry = {name, satno, country, orbit, rank, row, side}.
   */
  function _hrrGatherRows() {
    var entries = [];
    var tables = [
      { id: 'blue-hrr-list', side: 'blue' },
      { id: 'red-hrr-list',  side: 'red'  }
    ];
    tables.forEach(function(t) {
      var wrap = document.getElementById(t.id);
      if (!wrap) return;
      var tbl = wrap.querySelector('table.hrr-table');
      if (!tbl || !tbl.tBodies[0]) return;
      Array.from(tbl.tBodies[0].rows).forEach(function(row) {
        var cells = row.cells;
        if (cells.length < 5) return;
        entries.push({
          name:    (cells[0].textContent || '').trim(),
          satno:   (cells[1].textContent || '').trim(),
          country: (cells[2].textContent || '').trim(),
          orbit:   (cells[3].textContent || '').trim(),
          rank:    (cells[4].textContent || '').trim(),
          row:     row,
          side:    t.side
        });
      });
    });
    return entries;
  }

  var _hrrTimeout = null;

  window._hrrSearch = function(query) {
    clearTimeout(_hrrTimeout);
    _hrrTimeout = setTimeout(function() { _hrrDoSearch(query); }, 120);
  };

  function _hrrDoSearch(query) {
    var dropdown = document.getElementById('hrr-search-dropdown');
    if (!dropdown) return;

    query = (query || '').trim().toLowerCase();
    if (!query) {
      dropdown.innerHTML = '';
      dropdown.style.display = 'none';
      _hrrClearHighlight();
      return;
    }

    var entries = _hrrGatherRows();
    if (!entries.length) {
      dropdown.innerHTML = '<div class="hrr-dd-empty">No HRR data loaded — click Refresh first</div>';
      dropdown.style.display = '';
      return;
    }

    /* Score each entry: prefer prefix matches, then substring. */
    var scored = [];
    entries.forEach(function(e) {
      var haystack = (e.name + ' ' + e.satno + ' ' + e.country + ' ' + e.orbit).toLowerCase();
      var nameL = e.name.toLowerCase();
      var satnoL = e.satno.toLowerCase();
      var score = -1;
      if (nameL.indexOf(query) === 0)  score = 100;  /* name starts with */
      else if (satnoL.indexOf(query) === 0) score = 90; /* satno starts with */
      else if (nameL.indexOf(query) >= 0) score = 70;  /* name contains */
      else if (haystack.indexOf(query) >= 0) score = 50; /* any field contains */
      if (score > 0) scored.push({ e: e, score: score });
    });

    scored.sort(function(a, b) { return b.score - a.score; });
    var matches = scored.slice(0, 12);

    if (!matches.length) {
      dropdown.innerHTML = '<div class="hrr-dd-empty">No matches</div>';
      dropdown.style.display = '';
      return;
    }

    /* Built as DOM nodes, not as an HTML string.
       _hrrGatherRows reads each cell with textContent, which DECODES what
       Jinja escaped on the way out: a satellite name rendered into the table
       as &lt;img src=x onerror=...&gt; is live markup again by the time it
       reaches this function. Concatenating it into innerHTML executed it in
       the analyst's authenticated session as soon as they typed one matching
       character into the search box. Names reach the HRR tables from UDL and
       from manual entry, so the payload needed no privilege to plant.
       createTextNode and textContent cannot be talked out of treating their
       argument as text, which is why they are used for every field below. */
    dropdown.replaceChildren();
    matches.forEach(function(m, i) {
      var e = m.e;
      var item = document.createElement('div');
      item.className = 'hrr-dd-item '
                     + (e.side === 'red' ? 'hrr-dd-side-red' : 'hrr-dd-side-blue');
      item.dataset.idx = String(i);
      /* A listener rather than an onmousedown attribute: the attribute had to
         be assembled as markup, which is the habit this change removes. */
      item.addEventListener('mousedown', function() { window._hrrSelect(i); });

      var name = document.createElement('span');
      name.className = 'hrr-dd-name';
      _hrrAppendHighlighted(name, e.name, query);

      var meta = document.createElement('span');
      meta.className = 'hrr-dd-meta';
      meta.appendChild(document.createTextNode(
        e.satno + ' \u00b7 ' + e.country + ' \u00b7 ' + e.orbit
        + ' \u00b7 Rank ' + e.rank + ' \u00b7 '
      ));
      var side = document.createElement('em');
      side.textContent = e.side;
      meta.appendChild(side);

      item.appendChild(name);
      item.appendChild(meta);
      dropdown.appendChild(item);
    });
    dropdown.style.display = '';

    /* Stash matches for select handler. */
    window._hrrMatches = matches;
  }

  /* Appends *text* to *parent* with the matched run wrapped in <mark>.
     The predecessor returned an HTML string for the caller to concatenate,
     which is how the payload got in. This one builds the <mark> as an element
     and everything around it as text nodes, so there is no string for markup
     to hide in. */
  function _hrrAppendHighlighted(parent, text, query) {
    var idx = text.toLowerCase().indexOf(query);
    if (idx < 0) {
      parent.appendChild(document.createTextNode(text));
      return;
    }
    parent.appendChild(document.createTextNode(text.substring(0, idx)));
    var mark = document.createElement('mark');
    mark.textContent = text.substring(idx, idx + query.length);
    parent.appendChild(mark);
    parent.appendChild(document.createTextNode(text.substring(idx + query.length)));
  }

  window._hrrSelect = function(idx) {
    var matches = window._hrrMatches;
    if (!matches || !matches[idx]) return;
    var entry = matches[idx].e;
    var row = entry.row;

    /* Close dropdown and fill input with selection. */
    var dropdown = document.getElementById('hrr-search-dropdown');
    var input = document.getElementById('hrr-search-input');
    if (dropdown) dropdown.style.display = 'none';
    if (input) input.value = entry.name + ' (' + entry.satno + ')';

    /* Clear previous highlight, apply new one. */
    _hrrClearHighlight();
    row.classList.add('hrr-row-selected');

    /* Scroll the row into view within its scroll container. */
    var scrollParent = row.closest('.hrr-scroll');
    if (scrollParent) {
      scrollParent.scrollTop = row.offsetTop - scrollParent.offsetTop - 30;
    }
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  function _hrrClearHighlight() {
    document.querySelectorAll('.hrr-row-selected').forEach(function(el) {
      el.classList.remove('hrr-row-selected');
    });
  }

  /* Close dropdown when clicking outside. */
  document.addEventListener('click', function(e) {
    var wrap = document.getElementById('hrr-search-wrap');
    var dropdown = document.getElementById('hrr-search-dropdown');
    if (wrap && dropdown && !wrap.contains(e.target)) {
      dropdown.style.display = 'none';
    }
  });
})();
SPECTRE.action('hrrSearch', function (el) { window._hrrSearch(el.value); });

/* ── Theme switcher ─────────────────────────────────────────────────────── */
(function () {
  var THEMES = ['ops', 'steel'];
  var KEY    = 'spectre-theme';

  function spectreSetTheme(theme) {
    if (THEMES.indexOf(theme) === -1) return;        // only allow known themes
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.spectreTheme = theme === 'steel' ? 'light' : 'dark';
    try { localStorage.setItem(KEY, theme); } catch (_) {}
    var picker = document.getElementById('theme-picker');
    if (picker && picker.value !== theme) picker.value = theme;
  }

  window.spectreSetTheme = spectreSetTheme;

  /* Sync the dropdown to whatever theme is active (set from localStorage
     by theme-boot.js in <head> before first paint) */
  (function syncPicker() {
    var current = document.documentElement.dataset.theme || 'ops';
    var picker  = document.getElementById('theme-picker');
    if (picker) picker.value = current;
  })();
})();
SPECTRE.action('spectreSetTheme', function (el) { window.spectreSetTheme(el.value); });

/* ── Splash overlay (partials/splash_overlay.html) ──────────────────────────
   Shown once per browser session on console load, closed after 3.4 s or on a click or key press. On a later load
   in the session theme-boot.js marks the page before first paint and the stylesheet keeps the splash hidden, which
   is what the inline block's synchronous remove() did; this then removes the node. */
SPECTRE.init('splash', function (el) {
  var key = 'spectre-splash-seen';
  var seen = false;
  try { seen = !!sessionStorage.getItem(key); } catch (_) { seen = false; }
  if (seen) { el.remove(); return; }

  var timer = setTimeout(close, 3400);
  document.addEventListener('keydown', close, { once: true });

  function close() {
    clearTimeout(timer);
    document.removeEventListener('keydown', close);
    try { sessionStorage.setItem(key, '1'); } catch (_) { /* it shows again on the next load, nothing worse */ }
    el.style.opacity = '0';
    el.style.pointerEvents = 'none';
    setTimeout(function () { el.remove(); }, 650);
  }
  window.spectreCloseSplash = close;
});
SPECTRE.action('closeSplash', function () {
  if (typeof window.spectreCloseSplash === 'function') { window.spectreCloseSplash(); }
});

/* ── UDL connection chip (partials/udl_status.html) ─────────────────────────
   Each state of the status fragment carries data-chip-state and data-chip-label; the chip in the nav bar takes
   them, and a connection closes the dropdown it was opened from. */
SPECTRE.init('udl-chip', function (el) {
  var d = document.getElementById('udl-dropdown');
  if (!d) return;
  if (el.dataset.chipClose !== undefined) { d.removeAttribute('open'); }
  var dot = d.querySelector('.chip-dot');
  if (dot) dot.className = 'chip-dot dot-' + el.dataset.chipState;
  var lbl = d.querySelector('.chip-label');
  if (lbl) lbl.textContent = el.dataset.chipLabel;
});

/* ── Element-set refresh note (partials/elset_refresh_note.html) ────────────
   Once UDL has replaced held sets, the red card is redrawn with the new epoch. */
SPECTRE.init('reread-red-card', function () {
  if (typeof window.spectreRereadRedCard === 'function') { window.spectreRereadRedCard(); }
});

/* ── TLE fields (partials/tle_fields.html) ──────────────────────────────────
   Editing a fetched set makes it the operator's own, so the UDL data mode and provider it was tagged with are
   dropped. */
SPECTRE.action('dropElsetMode', function (el) {
  if (!el.form) { return; }
  el.form.querySelectorAll('[name=elset_mode], [name=elset_source]').forEach(function (tag) { tag.remove(); });
});

/* ── Red track and blue asset forms (operator.html) ─────────────────────────
   What hx-on::after-settle did, kept exactly: clear the satno box and the typed fields when an htmx:afterSettle
   reaching the form names the form as the element that made the request. In htmx 1.9.12 the form's own request
   swaps the list outside the form, so that event never reaches it and the fields are kept after an add, as they
   were before this change; that is recorded for the owner rather than changed here (SPC-199). */
SPECTRE.afterSettle('clearAssetForm', function (form, event) {
  if (!event.detail || event.detail.elt !== form) return;
  var satno = document.getElementById(form.dataset.satnoField);
  if (satno) { satno.value = ''; }
  form.querySelectorAll('input:not([type=radio]):not([type=hidden]),textarea').forEach(function (el) {
    el.value = '';
  });
});

/* ── Catalogue search (partials/catalog_results.html) ───────────────────────
   Sending an object to a side opens the first details of that side's panel, as hx-on::after-request did. */
SPECTRE.afterRequest('openSideDetails', function (button) {
  var details = document.querySelector('.panel-' + button.dataset.side + ' details');
  if (details) { details.setAttribute('open', ''); }
});

/* ── HRR watchlist tables (partials/hrr_panel.html) ───────────────────────── */
function hrrSort(th) {
  var table = th.closest('table');
  var col = th.cellIndex;
  var asc = th.dataset.dir !== 'asc';
  table.querySelectorAll('th').forEach(function(h) { h.dataset.dir = ''; });
  th.dataset.dir = asc ? 'asc' : 'desc';
  var tbody = table.querySelector('tbody');
  var rows = Array.from(tbody.rows);
  rows.sort(function(a, b) {
    var av = (a.cells[col].dataset.val !== undefined ? a.cells[col].dataset.val : a.cells[col].textContent).trim();
    var bv = (b.cells[col].dataset.val !== undefined ? b.cells[col].dataset.val : b.cells[col].textContent).trim();
    var an = Number.parseFloat(av), bn = Number.parseFloat(bv);
    if (!Number.isNaN(an) && !Number.isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  rows.forEach(function(r) { tbody.appendChild(r); });
  table.querySelectorAll('.hrr-sort-ind').forEach(function(s) { s.textContent = ''; });
  th.querySelector('.hrr-sort-ind').textContent = asc ? ' ▲' : ' ▼';
  /* Same fact as the glyph, for an operator who cannot see it. Only the
     headers that carry aria-sort are reset, so the leading actions column
     is never told it is an unsorted sortable column. */
  table.querySelectorAll('th[aria-sort]').forEach(function(h) { h.setAttribute('aria-sort', 'none'); });
  th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
}
SPECTRE.action('hrrSort', hrrSort);
