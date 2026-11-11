/* SPECTRE first-party script: the Decision Engine panel and its results (SPC-199).
 *
 * Moved from the inline blocks in partials/decision_panel.html and decision_results.html and the handlers on the
 * row controls and the histogram's cell select. The rows the panel adds used to be markup in a script string with
 * Jinja macros rendered into it; that markup is now a <template> in the panel, cloned here, and each row's number
 * is written where __ROW__ stands. The row counters live on the row containers, so a fresh panel starts from its
 * own count as the re-declared globals did.
 */

/* ── Add and remove rows ── */
function decisionAddRow(containerId, templateId) {
  var container = document.getElementById(containerId);
  var template = document.getElementById(templateId);
  if (!container || !template) return;
  var c = Number(container.getAttribute('data-row-count') || '0') + 1;
  container.setAttribute('data-row-count', String(c));
  var row = template.content.firstElementChild.cloneNode(true);
  row.querySelectorAll('input').forEach(function (input) {
    if (input.value.indexOf('__ROW__') !== -1) { input.value = input.value.replace('__ROW__', String(c)); }
  });
  container.appendChild(row);
}

SPECTRE.action('addAdvRow', function () { decisionAddRow('adv-rows', 'adv-row-template'); });
SPECTRE.action('addFrRow', function () { decisionAddRow('fr-rows', 'fr-row-template'); });
SPECTRE.action('removeRow', function (btn) {
  var row = btn.closest('.' + btn.getAttribute('data-row-class'));
  if (row) row.remove();
});

/* ── Which cell opened the trajectory view: every cell's trajectory form posts to the same view, so the one
   submitted is marked and the view's close and Escape return focus there. Listened for on this table, not on
   document. ── */
SPECTRE.init('geometry-opener', function (region) {
  var table = region.parentElement;
  if (!table) { return; }
  table.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.classList || !form.classList.contains('show-trajectory')) { return; }
    table.querySelectorAll('form.show-trajectory[data-geometry-opener]').forEach(function (f) {
      f.removeAttribute('data-geometry-opener');
    });
    form.setAttribute('data-geometry-opener', 'true');
  }, true);
});

/* ── Sampled times of closest approach: the histogram for the chosen cell ── */
var tcaHistogramChart = null;

function tcaHistogram(cell) {
  var block = document.getElementById('tca-hist-data-' + cell);
  document.querySelectorAll('.tca-histogram [data-cell]').forEach(function (el) {
    el.hidden = el.getAttribute('data-cell') !== cell;
  });
  if (!block || typeof Chart === 'undefined') { return; }
  var data = JSON.parse(block.textContent);
  /* The bars and the axis take the table's own text: its edges are stated exactly, so nothing here rounds a time. */
  var table = Array.prototype.find.call(document.querySelectorAll('.tca-histogram table[data-cell]'), function (t) {
    return t.getAttribute('data-cell') === cell;
  });
  var labels = table ? Array.prototype.map.call(table.querySelectorAll('tbody tr td:first-child'), function (td) { return td.textContent; }) : [];
  var axis = table ? table.querySelector('thead th').textContent : '';
  var styles = getComputedStyle(document.documentElement);
  var bar = styles.getPropertyValue('--ops-blue').trim();
  var dim = styles.getPropertyValue('--text-dim').trim();
  if (tcaHistogramChart) { tcaHistogramChart.destroy(); }
  tcaHistogramChart = new Chart(document.getElementById('tca-hist-chart'), {
    type: 'bar',
    data: { labels: labels, datasets: [{ label: 'Samples', data: data.counts, backgroundColor: bar }] },
    options: {
      animation: false, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: {
        x: { title: { display: true, text: axis, color: dim }, ticks: { color: dim } },
        y: { beginAtZero: true, title: { display: true, text: 'Samples', color: dim }, ticks: { color: dim, precision: 0 } }
      }
    }
  });
}

SPECTRE.action('tcaHistogram', function (select) { tcaHistogram(select.value); });
SPECTRE.init('tca-histogram', function () {
  /* A new results section draws on a new canvas, so the last section's chart is not destroyed for it. */
  tcaHistogramChart = null;
  var select = document.getElementById('tca-hist-cell');
  if (select) { tcaHistogram(select.value); }
});
