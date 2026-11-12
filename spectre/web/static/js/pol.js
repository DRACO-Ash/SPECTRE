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
function polCharts(marker) {
  var SATNO   = marker.dataset.satno;
  var IS_GEO  = marker.dataset.geo === 'true';

  var ZOOM_CFG = {
    pan:  { enabled: true, mode: 'xy' },
    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'xy' }
  };

  var CHART_DEFAULTS = {
    animation: false,
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
      legend: { display: false },
      zoom: ZOOM_CFG,
    },
    scales: {
      x: { ticks: { color: '#8899aa', font: { size: 9 }, maxTicksLimit: 8, maxRotation: 0 },
           grid: { color: 'rgba(255,255,255,0.04)' } },
      y: { ticks: { color: '#8899aa', font: { size: 9 } },
           grid: { color: 'rgba(255,255,255,0.04)' } }
    }
  };

  function deepMerge(base, over) {
    var out = Object.assign({}, base);
    for (var k in over) {
      if (over[k] && typeof over[k] === 'object' && !Array.isArray(over[k])) {
        out[k] = deepMerge(base[k] || {}, over[k]);
      } else { out[k] = over[k]; }
    }
    return out;
  }

  // Create a chart and wire dblclick → resetZoom
  function mkChart(ctx, config) {
    var chart = new Chart(ctx, config);
    ctx.addEventListener('dblclick', function () { chart.resetZoom(); });
    ctx.title = 'Scroll to zoom · Drag to pan · Double-click to reset';
    return chart;
  }

  function sparkLine(id, labels, data, color) {
    var ctx = document.getElementById(id);
    if (!ctx) return;
    return mkChart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: [{ data: data, borderColor: color, borderWidth: 1.2,
              pointRadius: 0, fill: false, tension: 0 }] },
      options: deepMerge(CHART_DEFAULTS, { plugins: { legend: { display: false } } })
    });
  }

  function makeHistogram(values, bins) {
    if (!values || !values.length) return { labels: [], counts: [] };
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    if (min === max) { min -= 1; max += 1; }
    var w = (max - min) / bins, counts = new Array(bins).fill(0), labels = [];
    for (var i = 0; i < bins; i++) labels.push((min + i * w).toFixed(1));
    values.forEach(function (v) { counts[Math.min(bins - 1, Math.floor((v - min) / w))]++; });
    return { labels: labels, counts: counts };
  }

  function findNearestIdx(epochs, dateStr) {
    var target = new Date(dateStr).getTime();
    var best = 0, bestDiff = Infinity;
    epochs.forEach(function (e, i) {
      var diff = Math.abs(new Date(e).getTime() - target);
      if (diff < bestDiff) { bestDiff = diff; best = i; }
    });
    return best;
  }

  // ── Fetch all chart data ────────────────────────────────────────────────────
  fetch('/pol/chart-data/' + SATNO)
    .then(function (r) { return r.json(); })
    .then(function (d) {

      var eps = d.elements ? d.elements.epochs : [];

      // ── Element sparklines ───────────────────────────────────────────────
      if (d.elements) {
        sparkLine('pol-alt-chart',    eps, d.elements.altitude,     '#3b8beb');
        sparkLine('pol-inc-chart',    eps, d.elements.inclination,  '#22c55e');
        sparkLine('pol-ecc-chart',    eps, d.elements.eccentricity, '#f59e0b');
        sparkLine('pol-raan-chart',   eps, d.elements.raan,         '#a78bfa');
      }

      // ── Period sparkline (§6 side chart) ────────────────────────────────
      if (d.elements && d.elements.period) {
        sparkLine('pol-period-chart', eps, d.elements.period, '#e879f9');
      }

      // ── ΔV Timeline ─────────────────────────────────────────────────────
      var dvCtx = document.getElementById('pol-dv-chart');
      if (dvCtx && d.manoeuvres && d.manoeuvres.epochs.length) {
        mkChart(dvCtx, {
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
          options: deepMerge(CHART_DEFAULTS, {
            scales: { y: { title: { display: true, text: 'ΔV (m/s)', color: '#8899aa', font: { size: 9 } } } }
          })
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
      } else if (dvCtx) {
        dvCtx.parentNode.innerHTML += '<p class="empty-msg" style="font-size:0.68rem">No manoeuvres to chart.</p>';
      }

      // ── GEO Longitude Timeline ──────────────────────────────────────────
      var lonCtx = document.getElementById('pol-lon-chart');
      if (IS_GEO && lonCtx && d.geo && d.geo.longitude && d.geo.longitude.length) {
        var geoEps  = d.geo.epochs;
        var geoLons = d.geo.longitude;
        var phases  = d.geo.drift_phases || [];

        // Build segment color lookup from drift phases
        var phaseRanges = phases.map(function (ph) {
          return {
            startIdx: findNearestIdx(geoEps, ph.start),
            endIdx:   findNearestIdx(geoEps, ph.end),
            direction: ph.direction
          };
        });

        function segColorForIdx(idx) {
          for (var i = 0; i < phaseRanges.length; i++) {
            if (idx >= phaseRanges[i].startIdx && idx <= phaseRanges[i].endIdx) {
              return phaseRanges[i].direction === 'EAST' ? '#22c55e' :
                     phaseRanges[i].direction === 'WEST' ? '#ef4444' : '#6b7280';
            }
          }
          return '#8899aa';
        }

        // Manoeuvre scatter points on longitude
        var mnvLons = (d.manoeuvres && d.manoeuvres.lons) ? d.manoeuvres.lons : [];
        var mnvEps  = (d.manoeuvres && d.manoeuvres.epochs) ? d.manoeuvres.epochs : [];
        var scatterData = [];
        mnvEps.forEach(function (e, i) {
          if (mnvLons[i] !== null && mnvLons[i] !== undefined) {
            scatterData.push({ x: e, y: mnvLons[i] });
          }
        });

        mkChart(lonCtx, {
          type: 'line',
          data: {
            labels: geoEps,
            datasets: [
              {
                data: geoLons,
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
          options: deepMerge(CHART_DEFAULTS, {
            scales: {
              x: { type: 'category' },
              y: { title: { display: true, text: 'Longitude (°)', color: '#8899aa', font: { size: 9 } } }
            }
          })
        });
      }

      // ── Drift Rate Timeline ─────────────────────────────────────────────
      var drCtx = document.getElementById('pol-drift-chart');
      if (IS_GEO && drCtx && d.geo && d.geo.drift_rate && d.geo.drift_rate.length) {
        var nonZero = d.geo.drift_rate.filter(function (v) { return v !== 0; });
        if (nonZero.length > 0) {
          mkChart(drCtx, {
            type: 'line',
            data: {
              labels: d.geo.epochs,
              datasets: [
                { data: d.geo.drift_rate, borderColor: '#8899aa', borderWidth: 1,
                  pointRadius: 0, fill: false, tension: 0,
                  segment: { borderColor: function (ctx) {
                    var v = d.geo.drift_rate[ctx.p0DataIndex] || 0;
                    return v > 0.05 ? '#22c55e' : v < -0.05 ? '#ef4444' : '#6b7280';
                  }}
                },
                // Zero reference line
                { data: d.geo.epochs.map(function () { return 0; }),
                  borderColor: 'rgba(255,255,255,0.15)', borderWidth: 1,
                  borderDash: [4, 3], pointRadius: 0, fill: false }
              ]
            },
            options: deepMerge(CHART_DEFAULTS, {
              scales: {
                y: { title: { display: true, text: '°/day', color: '#8899aa', font: { size: 9 } } }
              }
            })
          });
        }
      }

      // ── ΔV Histogram ────────────────────────────────────────────────────
      var dvHistCtx = document.getElementById('pol-dv-hist');
      if (dvHistCtx && d.manoeuvres && d.manoeuvres.dvs_ms && d.manoeuvres.dvs_ms.length >= 3) {
        var hDv = makeHistogram(d.manoeuvres.dvs_ms, 10);
        mkChart(dvHistCtx, {
          type: 'bar',
          data: { labels: hDv.labels,
                  datasets: [{ data: hDv.counts, backgroundColor: 'rgba(59,139,235,0.6)',
                               borderColor: '#3b8beb', borderWidth: 1, borderRadius: 2 }] },
          options: deepMerge(CHART_DEFAULTS, {
            scales: { x: { title: { display: true, text: 'ΔV (m/s)', color: '#8899aa', font: { size: 9 } } },
                      y: { title: { display: true, text: 'Count',    color: '#8899aa', font: { size: 9 } } } }
          })
        });
      }

      // ── Interval Histogram ──────────────────────────────────────────────
      var ivCtx = document.getElementById('pol-interval-hist');
      if (ivCtx && d.manoeuvres && d.manoeuvres.epochs && d.manoeuvres.epochs.length >= 3) {
        var mEps = d.manoeuvres.epochs;
        var intervals = [];
        for (var ii = 1; ii < mEps.length; ii++) {
          intervals.push((new Date(mEps[ii]) - new Date(mEps[ii - 1])) / 86400000);
        }
        if (intervals.length >= 2) {
          var hIv = makeHistogram(intervals, 10);
          mkChart(ivCtx, {
            type: 'bar',
            data: { labels: hIv.labels,
                    datasets: [{ data: hIv.counts, backgroundColor: 'rgba(34,197,94,0.6)',
                                 borderColor: '#22c55e', borderWidth: 1, borderRadius: 2 }] },
            options: deepMerge(CHART_DEFAULTS, {
              scales: { x: { title: { display: true, text: 'Days', color: '#8899aa', font: { size: 9 } } },
                        y: { title: { display: true, text: 'Count', color: '#8899aa', font: { size: 9 } } } }
            })
          });
        }
      }

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
