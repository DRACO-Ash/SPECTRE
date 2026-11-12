/* SPECTRE first-party script: the GCAT panel and its tables (SPC-199).
 *
 * Moved from the inline blocks in partials/gcat_panel.html and gcat_table.html and the handlers on the category
 * tabs, dataset buttons and the clear control. The dataset a table shows comes from its marker's data-dataset,
 * where Jinja used to write it into the script.
 */

/** Switch visible category group in the dataset nav. */
function gcatCatTab(btn) {
  var cat = btn.dataset.cat;
  document.querySelectorAll('.gcat-ctab').forEach(function(b) {
    b.classList.toggle('active', b === btn);
  });
  document.querySelectorAll('.gcat-nav-group').forEach(function(g) {
    g.classList.toggle('active', g.dataset.catGroup === cat);
  });
}

/** Mark the clicked dataset button active; clear others. */
function gcatSelectDs(btn) {
  document.querySelectorAll('.gcat-ds-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  btn.classList.add('active');
}

/** Clear search and reload the current dataset from page 1.
 *  Called by the ✕ button in the table toolbar. */
function gcatClearSearch(dsKey) {
  htmx.ajax('GET', '/gcat/table?dataset=' + encodeURIComponent(dsKey) + '&q=&page=1', {
    target: '#gcat-table-area',
    swap: 'innerHTML',
    indicator: '#gcat-load-ind'
  });
}

/** Sync nav active state after a table swap, and show the dataset's category group if needed. */
function gcatSync(dsKey) {
  document.querySelectorAll('.gcat-ds-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.ds === dsKey);
  });
  var btn = Array.prototype.find.call(document.querySelectorAll('.gcat-ds-btn'), function (b) {
    return b.dataset.ds === dsKey;
  });
  if (!btn) return;
  var cat = btn.dataset.cat;
  if (!cat) return;
  document.querySelectorAll('.gcat-nav-group').forEach(function(g) {
    if (g.dataset.catGroup === cat && !g.classList.contains('active')) {
      /* Switch category tab to match the selected dataset */
      g.classList.add('active');
      var tab = Array.prototype.find.call(document.querySelectorAll('.gcat-ctab'), function (t) {
        return t.dataset.cat === cat;
      });
      if (tab) {
        document.querySelectorAll('.gcat-ctab').forEach(function(t) { t.classList.remove('active'); });
        tab.classList.add('active');
      }
    }
  });
}

SPECTRE.action('gcatCatTab', gcatCatTab);
SPECTRE.action('gcatSelectDs', gcatSelectDs);
SPECTRE.action('gcatClearSearch', function (el) { gcatClearSearch(el.dataset.dataset); });
SPECTRE.init('gcat-sync', function (marker) { gcatSync(marker.dataset.dataset); });
