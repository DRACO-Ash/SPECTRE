/* SPECTRE first-party script: the pattern-of-life panel and its results (SPC-199).
 *
 * Moved from the inline blocks in partials/pol_panel.html and pol_results.html and the handlers on the results'
 * headers. The object and whether it is GEO come from the results' marker element, where Jinja used to write them
 * into the script.
 */

/* ── Source radios: each shows its own panel ── */
SPECTRE.action('polSource', function (radio) {
  document.querySelectorAll('.pol-src-panel').forEach(function(p) { p.style.display = 'none'; });
  var panel = document.getElementById('pol-src-' + radio.value);
  if (panel) panel.style.display = '';
});

/* ── Results: the charts, drawn from /pol/chart-data/<satno> ── */
var POL_CHART_DEFAULTS = {
  animation: false,
  responsive: true,
  maintainAspectRatio: true,
  plugins: {
    legend: { display: false },
    zoom: {
      pan:  { enabled: true, mode: 'xy' },
      zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'xy' }
    },
  },
  scales: {
    x: { ticks: { color: '#8899aa', font: { size: 9 }, maxTicksLimit: 8, maxRotation: 0 },
         grid: { color: 'rgba(255,255,255,0.04)' } },
    y: { ticks: { color: '#8899aa', font: { size: 9 } },
         grid: { color: 'rgba(255,255,255,0.04)' } }
  }
};

function polDeepMerge(base, over) {
  var out = { ...base };
  for (var k in over) {
    if (over[k] && typeof over[k] === 'object' && !Array.isArray(over[k])) {
      out[k] = polDeepMerge(base[k] || {}, over[k]);
    } else { out[k] = over[k]; }
  }
  return out;
}

/* The chart options: the panel's defaults with this chart's own on top. */
function polOptions(over) {
  return polDeepMerge(POL_CHART_DEFAULTS, over);
}

/* An axis title in the panel's muted style. */
function polAxisTitle(text) {
  return { title: { display: true, text: text, color: '#8899aa', font: { size: 9 } } };
}

// Create a chart and wire dblclick → resetZoom
function polChart(ctx, config) {
  var chart = new Chart(ctx, config);
  ctx.addEventListener('dblclick', function () { chart.resetZoom(); });
  ctx.title = 'Scroll to zoom · Drag to pan · Double-click to reset';
  return chart;
}

function polSparkLine(id, labels, data, color) {
  var ctx = document.getElementById(id);
  if (!ctx) return;
  return polChart(ctx, {
    type: 'line',
    data: { labels: labels, datasets: [{ data: data, borderColor: color, borderWidth: 1.2,
            pointRadius: 0, fill: false, tension: 0 }] },
    options: polOptions({ plugins: { legend: { display: false } } })
  });
}

function polHistogram(values, bins) {
  if (!values?.length) return { labels: [], counts: [] };
  var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
  if (min === max) { min -= 1; max += 1; }
  var w = (max - min) / bins, counts = new Array(bins).fill(0), labels = [];
  for (var i = 0; i < bins; i++) labels.push((min + i * w).toFixed(1));
  values.forEach(function (v) { counts[Math.min(bins - 1, Math.floor((v - min) / w))]++; });
  return { labels: labels, counts: counts };
}

/* A histogram bar chart of the values, ten bins wide. */
function polHistogramChart(ctx, values, colour, fill, xLabel) {
  var h = polHistogram(values, 10);
  polChart(ctx, {
    type: 'bar',
    data: { labels: h.labels,
            datasets: [{ data: h.counts, backgroundColor: fill,
                         borderColor: colour, borderWidth: 1, borderRadius: 2 }] },
    options: polOptions({ scales: { x: polAxisTitle(xLabel), y: polAxisTitle('Count') } })
  });
}

function polNearestIdx(epochs, dateStr) {
  var target = new Date(dateStr).getTime();
  var best = 0, bestDiff = Infinity;
  epochs.forEach(function (e, i) {
    var diff = Math.abs(new Date(e).getTime() - target);
    if (diff < bestDiff) { bestDiff = diff; best = i; }
  });
  return best;
}

function polDirectionColour(direction) {
  if (direction === 'EAST') return '#22c55e';
  if (direction === 'WEST') return '#ef4444';
  return '#6b7280';
}

function polDriftColour(rate) {
  if (rate > 0.05) return '#22c55e';
  if (rate < -0.05) return '#ef4444';
  return '#6b7280';
}

// ── Element sparklines, and the period beside them (§6 side chart) ────────
function polElementCharts(d) {
  if (!d.elements) return;
  var eps = d.elements.epochs;
  polSparkLine('pol-alt-chart',    eps, d.elements.altitude,     '#3b8beb');
  polSparkLine('pol-inc-chart',    eps, d.elements.inclination,  '#22c55e');
  polSparkLine('pol-ecc-chart',    eps, d.elements.eccentricity, '#f59e0b');
  polSparkLine('pol-raan-chart',   eps, d.elements.raan,         '#a78bfa');
  if (d.elements.period) {
    polSparkLine('pol-period-chart', eps, d.elements.period, '#e879f9');
  }
}

// ── ΔV Timeline ─────────────────────────────────────────────────────────
function polDvTimeline(d) {
  var dvCtx = document.getElementById('pol-dv-chart');
  if (!dvCtx) return;
  if (!d.manoeuvres?.epochs.length) {
    dvCtx.parentNode.innerHTML += '<p class="empty-msg" style="font-size:0.68rem">No manoeuvres to chart.</p>';
    return;
  }
  polChart(dvCtx, {
    type: 'bar',
    data: {
      labels: d.manoeuvres.epochs,
      datasets: [{
        data: d.manoeuvres.dvs_ms,
        backgroundColor: d.manoeuvres.colors,
        borderColor:     d.manoeuvres.colors,
        borderWidth: 1, borderRadius: 2
      }]
    },
    options: polOptions({ scales: { y: polAxisTitle('ΔV (m/s)') } })
  });
  // Manual legend
  var leg = document.createElement('div');
  leg.style.cssText = 'display:flex;gap:0.8rem;flex-wrap:wrap;margin-top:0.3rem;font-size:0.6rem;color:#8899aa';
  [['#3b8beb','Station Keeping'], ['#f59e0b','Plane Change'], ['#ef4444','Repositioning'], ['#6b7280','Unknown']].forEach(function (p) {
    var s = document.createElement('span');
    s.innerHTML = '<span style="display:inline-block;width:10px;height:3px;border-radius:2px;background:' + p[0] + ';margin-right:3px;vertical-align:middle"></span>' + p[1];
    leg.appendChild(s);
  });
  dvCtx.parentNode.appendChild(leg);
}

// ── GEO Longitude Timeline ──────────────────────────────────────────────
function polLongitudeChart(d) {
  var lonCtx = document.getElementById('pol-lon-chart');
  if (!lonCtx || !d.geo?.longitude?.length) return;
  var geoEps  = d.geo.epochs;
  var phases  = d.geo.drift_phases || [];

  // Build segment color lookup from drift phases
  var phaseRanges = phases.map(function (ph) {
    return {
      startIdx: polNearestIdx(geoEps, ph.start),
      endIdx:   polNearestIdx(geoEps, ph.end),
      direction: ph.direction
    };
  });

  function segColorForIdx(idx) {
    for (var range of phaseRanges) {
      if (idx >= range.startIdx && idx <= range.endIdx) {
        return polDirectionColour(range.direction);
      }
    }
    return '#8899aa';
  }

  // Manoeuvre scatter points on longitude
  var mnvLons = d.manoeuvres?.lons || [];
  var mnvEps  = d.manoeuvres?.epochs || [];
  var scatterData = [];
  mnvEps.forEach(function (e, i) {
    if (mnvLons[i] !== null && mnvLons[i] !== undefined) {
      scatterData.push({ x: e, y: mnvLons[i] });
    }
  });

  polChart(lonCtx, {
    type: 'line',
    data: {
      labels: geoEps,
      datasets: [
        {
          data: d.geo.longitude,
          borderColor: '#8899aa',
          borderWidth: 1.4,
          pointRadius: 0,
          fill: false,
          tension: 0,
          segment: {
            borderColor: function (ctx) { return segColorForIdx(ctx.p0DataIndex); }
          }
        },
        {
          type: 'scatter',
          data: scatterData,
          pointRadius: 5,
          pointStyle: 'triangle',
          backgroundColor: 'rgba(245,158,11,0.85)',
          borderColor: '#f59e0b',
          borderWidth: 1,
          showLine: false
        }
      ]
    },
    options: polOptions({ scales: { x: { type: 'category' }, y: polAxisTitle('Longitude (°)') } })
  });
}

// ── Drift Rate Timeline ─────────────────────────────────────────────────
function polDriftChart(d) {
  var drCtx = document.getElementById('pol-drift-chart');
  if (!drCtx || !d.geo?.drift_rate?.length) return;
  var rates = d.geo.drift_rate;
  if (!rates.some(function (v) { return v !== 0; })) return;
  polChart(drCtx, {
    type: 'line',
    data: {
      labels: d.geo.epochs,
      datasets: [
        { data: rates, borderColor: '#8899aa', borderWidth: 1,
          pointRadius: 0, fill: false, tension: 0,
          segment: { borderColor: function (ctx) { return polDriftColour(rates[ctx.p0DataIndex] || 0); } }
        },
        // Zero reference line
        { data: d.geo.epochs.map(function () { return 0; }),
          borderColor: 'rgba(255,255,255,0.15)', borderWidth: 1,
          borderDash: [4, 3], pointRadius: 0, fill: false }
      ]
    },
    options: polOptions({ scales: { y: polAxisTitle('°/day') } })
  });
}

// ── ΔV Histogram ────────────────────────────────────────────────────────
function polDvHistogram(d) {
  var dvHistCtx = document.getElementById('pol-dv-hist');
  if (dvHistCtx && (d.manoeuvres?.dvs_ms?.length ?? 0) >= 3) {
    polHistogramChart(dvHistCtx, d.manoeuvres.dvs_ms, '#3b8beb', 'rgba(59,139,235,0.6)', 'ΔV (m/s)');
  }
}

// ── Interval Histogram ──────────────────────────────────────────────────
function polIntervalHistogram(d) {
  var ivCtx = document.getElementById('pol-interval-hist');
  var mEps = d.manoeuvres?.epochs;
  if (!ivCtx || (mEps?.length ?? 0) < 3) return;
  var intervals = [];
  for (var ii = 1; ii < mEps.length; ii++) {
    intervals.push((new Date(mEps[ii]) - new Date(mEps[ii - 1])) / 86400000);
  }
  polHistogramChart(ivCtx, intervals, '#22c55e', 'rgba(34,197,94,0.6)', 'Days');
}

function polCharts(marker) {
  var SATNO   = marker.dataset.satno;
  var IS_GEO  = marker.dataset.geo === 'true';

  // ── Fetch all chart data ────────────────────────────────────────────────────
  fetch('/pol/chart-data/' + SATNO)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      polElementCharts(d);
      polDvTimeline(d);
      if (IS_GEO) {
        polLongitudeChart(d);
        polDriftChart(d);
      }
      polDvHistogram(d);
      polIntervalHistogram(d);
    })
    .catch(function (e) { console.warn('PoL chart-data fetch failed:', e); });
}
SPECTRE.init('pol-charts', polCharts);

// ── Sortable table helper ─────────────────────────────────────────────────
function polSort(th) {
  var table = th.closest('table');
  var col   = th.cellIndex;
  var asc   = th.dataset.dir !== 'asc';
  table.querySelectorAll('th').forEach(function (h) { h.dataset.dir = ''; });
  th.dataset.dir = asc ? 'asc' : 'desc';
  var tbody = table.querySelector('tbody');
  var rows  = Array.from(tbody.rows);
  rows.sort(function (a, b) {
    var av = (a.cells[col].dataset.val !== undefined ? a.cells[col].dataset.val : a.cells[col].textContent).trim();
    var bv = (b.cells[col].dataset.val !== undefined ? b.cells[col].dataset.val : b.cells[col].textContent).trim();
    var an = Number.parseFloat(av), bn = Number.parseFloat(bv);
    if (!Number.isNaN(an) && !Number.isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  rows.forEach(function (r) { tbody.appendChild(r); });
  table.querySelectorAll('.hrr-sort-ind').forEach(function (s) { s.textContent = ''; });
  th.querySelector('.hrr-sort-ind').textContent = asc ? ' ▲' : ' ▼';
}
SPECTRE.action('polSort', polSort);
