/* SPECTRE first-party script: the threat sweep and asset screening fragments (SPC-199).
 *
 * Moved from the inline block in partials/threat_sweep.html, the one in partials/threat_screen.html, and the
 * handlers on their rows, headers and controls. Each sort's state used to be a variable the fragment's own block
 * declared afresh on every swap; it is now held on the table it sorts, so a new sweep still starts unsorted.
 */

/* ── Toggle a single target group ── */
function threatToggle(gIdx) {
  var rows = document.querySelectorAll('.threat-children-' + gIdx);
  var chevron = document.getElementById('chevron-' + gIdx);
  var visible = rows.length > 0 && rows[0].style.display !== 'none';
  rows.forEach(function(r) { r.style.display = visible ? 'none' : ''; });
  if (chevron) chevron.classList.toggle('is-open', !visible);
  /* The chevron's rotation carries the state for sighted operators
     only. aria-expanded is the same fact for everyone else, and it has to
     move with the rows rather than being set once in the markup. */
  var parent = document.getElementById('threat-group-' + gIdx);
  if (parent) parent.setAttribute('aria-expanded', visible ? 'false' : 'true');
}

/* ── Expand / Collapse all ── */
function threatExpandAll() {
  document.querySelectorAll('.threat-child').forEach(function(r) { r.style.display = ''; });
  document.querySelectorAll('svg.threat-chevron').forEach(function(c) { c.classList.add('is-open'); });
  _threatSetAllExpanded(true);
}
function threatCollapseAll() {
  document.querySelectorAll('.threat-child').forEach(function(r) { r.style.display = 'none'; });
  document.querySelectorAll('svg.threat-chevron').forEach(function(c) { c.classList.remove('is-open'); });
  _threatSetAllExpanded(false);
}
/* Expand-all and collapse-all move every row, so they have to move every
   state with them. Setting it in threatToggle alone would leave the
   announcement stale for every row these two touch. */
function _threatSetAllExpanded(expanded) {
  document.querySelectorAll('.threat-parent').forEach(function(row) {
    row.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  });
}

/* ── Search filter (matches parent target name + all child content) ── */
function threatFilter(q) {
  var term = q.trim().toLowerCase();
  /* Iterate parent rows */
  document.querySelectorAll('.threat-parent').forEach(function(parent) {
    var gIdx = parent.id.replace('threat-group-', '');
    var children = document.querySelectorAll('.threat-children-' + gIdx);
    var parentText = parent.textContent.toLowerCase();
    var childTexts = Array.from(children).map(function(r) { return r.textContent.toLowerCase(); });
    var allText = parentText + ' ' + childTexts.join(' ');
    var match = term === '' || allText.indexOf(term) !== -1;
    parent.style.display = match ? '' : 'none';
    /* Hide children if parent is hidden; otherwise preserve their toggle state */
    if (!match) {
      children.forEach(function(r) { r.style.display = 'none'; });
    }
  });
}

/* ── Data Mode filter (show only rows matching a UDL dataMode tag) ── */
function sweepDmFilter(val) {
  document.querySelectorAll('.threat-parent').forEach(function(parent) {
    var dm = (parent.dataset.dm || '').toUpperCase();
    var match = val === '' || dm === val.toUpperCase();
    parent.style.display = match ? '' : 'none';
    var gIdx = parent.id.replace('threat-group-', '');
    if (!match) {
      document.querySelectorAll('.threat-children-' + gIdx).forEach(function(r) {
        r.style.display = 'none';
      });
    }
  });
}

/* ── Sort child rows within a single group ── */
function childSort(gIdx, col, type) {
  var table = document.getElementById('threat-sweep-table');
  if (!table) return;
  /* { groupIdx: { col, asc } }, held on this sweep's table */
  var states = table.spectreChildSort || (table.spectreChildSort = {});
  var state = states[gIdx] || { col: -1, asc: true };
  if (state.col === col) { state.asc = !state.asc; }
  else { state.col = col; state.asc = true; }
  states[gIdx] = state;

  /* Collect only data rows (skip the header row) for this group */
  var all = document.querySelectorAll('.threat-children-' + gIdx);
  var headerRow = null;
  var dataRows = [];
  all.forEach(function(r) {
    if (r.classList.contains('threat-child-header')) { headerRow = r; }
    /* Only the real child rows carry a threat-row- id. The PAIR intel row is
       also .threat-children-N but it is a single cell with colspan="8", so
       a.cells[col] came back undefined and the comparator threw on
       .textContent: for every group that had target intel, child sort did
       nothing at all, and an aria-sort written after the sort would never
       have been reached. */
    else if (r.id.indexOf('threat-row-') === 0) { dataRows.push(r); }
  });

  dataRows.sort(function(a, b) {
    var av = a.cells[col].textContent.trim();
    var bv = b.cells[col].textContent.trim();
    if (type === 'num') { av = Number.parseFloat(av) || 0; bv = Number.parseFloat(bv) || 0; }
    if (av < bv) return state.asc ? -1 : 1;
    if (av > bv) return state.asc ? 1 : -1;
    return 0;
  });

  /* Re-insert after the header row */
  var ref = headerRow;
  dataRows.forEach(function(r) {
    ref.parentNode.insertBefore(r, ref.nextSibling);
    ref = r;
  });

  /* Say which column is sorted and which way, to the eye and to the
     accessibility tree, and only within THIS group's header row: each
     expanded group sorts independently, so a shared reset would wipe the
     state of a group the operator did not touch. */
  if (headerRow) {
    headerRow.querySelectorAll('th').forEach(function(h) {
      if (h.hasAttribute('aria-sort')) { h.setAttribute('aria-sort', 'none'); }
      var i = h.querySelector('.hrr-sort-ind');
      if (i) { i.textContent = ''; }
    });
    var th = headerRow.querySelector('#tsw-child-' + gIdx + '-' + col);
    if (th) {
      th.setAttribute('aria-sort', state.asc ? 'ascending' : 'descending');
      var ind = th.querySelector('.hrr-sort-ind');
      if (ind) { ind.textContent = state.asc ? ' ▲' : ' ▼'; }
    }
  }
}

/* ── Sort parent rows (re-orders groups in the table) ── */
function threatSort(col, type) {
  var table = document.getElementById('threat-sweep-table');
  if (!table) return;
  var tbody = table.tBodies[0];
  var sort = table.spectreSort || (table.spectreSort = { col: -1, asc: true });

  if (sort.col === col) { sort.asc = !sort.asc; }
  else { sort.col = col; sort.asc = true; }

  /* Which column is sorted and which way — glyph and aria-sort written
     together, from one branch, so they cannot disagree. */
  var ths = table.querySelectorAll('thead th');
  ths.forEach(function(h) {
    if (h.hasAttribute('aria-sort')) { h.setAttribute('aria-sort', 'none'); }
    var i = h.querySelector('.hrr-sort-ind');
    if (i) { i.textContent = ''; }
  });
  var sortedTh = ths[col];
  if (sortedTh) {
    sortedTh.setAttribute('aria-sort', sort.asc ? 'ascending' : 'descending');
    var sortedInd = sortedTh.querySelector('.hrr-sort-ind');
    if (sortedInd) { sortedInd.textContent = sort.asc ? ' ▲' : ' ▼'; }
  }

  /* Collect groups: each group = [parentRow, ...childRows] */
  var groups = [];
  var currentGroup = null;
  Array.from(tbody.rows).forEach(function(row) {
    if (row.classList.contains('threat-parent')) {
      currentGroup = [row];
      groups.push(currentGroup);
    } else if (currentGroup) {
      currentGroup.push(row);
    }
  });

  /* Sort groups by the parent row's cell value */
  groups.sort(function(a, b) {
    var av = a[0].cells[col].textContent.trim();
    var bv = b[0].cells[col].textContent.trim();
    if (type === 'num') { av = Number.parseFloat(av) || 0; bv = Number.parseFloat(bv) || 0; }
    if (av < bv) return sort.asc ? -1 : 1;
    if (av > bv) return sort.asc ? 1 : -1;
    return 0;
  });

  /* Re-append in sorted order */
  groups.forEach(function(group) {
    group.forEach(function(row) { tbody.appendChild(row); });
  });
}

/* ── Load solution into the intercept engine ── */
function loadInEngine(redSat, blueSat, epoch, method) {
  if (typeof SPECTRE.switchToEngine === 'function') SPECTRE.switchToEngine();
  var redSel = document.getElementById('ie-red-sat');
  var blueSel = document.getElementById('ie-blue-sat');
  var methodSel = document.getElementById('ie-method');
  var startInput = document.querySelector('input[name="manoeuvre_start"]');
  if (redSel) { redSel.value = redSat; }
  if (blueSel) { blueSel.value = blueSat; }
  if (methodSel) {
    methodSel.value = method;
    if (typeof window.ieUpdate === 'function') window.ieUpdate();
  }
  if (startInput) { startInput.value = epoch; }
  var engine = document.getElementById('intercept-engine-form');
  if (engine) engine.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* ── Asset screening: open one actor's profiles ── */
function scrToggle(cls) {
  document.querySelectorAll('.scr-child.' + cls).forEach(function (row) {
    row.style.display = row.style.display === 'none' ? '' : 'none';
  });
}

/* A header or row names its column, sort kind and group in data-col, data-kind and data-group; a Load control
   carries its red, blue, epoch and method in data-*, as it did for the handler it replaces. */
SPECTRE.action('threatToggle', function (el) { threatToggle(Number(el.dataset.idx)); });
SPECTRE.action('threatExpandAll', function () { threatExpandAll(); });
SPECTRE.action('threatCollapseAll', function () { threatCollapseAll(); });
SPECTRE.action('threatFilter', function (el) { threatFilter(el.value); });
SPECTRE.action('sweepDmFilter', function (el) { sweepDmFilter(el.value); });
SPECTRE.action('threatSort', function (el) { threatSort(Number(el.dataset.col), el.dataset.kind); });
SPECTRE.action('childSort', function (el) {
  childSort(Number(el.dataset.group), Number(el.dataset.col), el.dataset.kind);
});
SPECTRE.action('loadInEngine', function (el) {
  loadInEngine(el.dataset.red, el.dataset.blue, el.dataset.epoch, el.dataset.method);
});
SPECTRE.action('scrToggle', function (el) { scrToggle(el.dataset.row); });

/* ── Sweep target config: the manual target fields clear once the add has succeeded, as hx-on::after-request did.
   Cleared after the request, never on click: cleared on click they were empty before htmx read them. */
SPECTRE.afterRequest('clearManualTarget', function (button, event) {
  if (!event.detail.successful) return;
  document.getElementById('ts-manual-name').value = '';
  document.getElementById('ts-manual-tle').value = '';
});
