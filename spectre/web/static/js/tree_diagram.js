/* SPECTRE first-party script: the game tree drawn (SPC-190).
 *
 * The drawing is SVG written on the server (partials/decision_tree.html, laid out by web/tree_view.py), and it shows
 * in full without this script, its controls hidden, so no control is offered that cannot work. This script shows
 * them and makes them work:
 *   each box with branches after it gets a control, a button in the tab order that a click, Enter or Space works,
 *   which collapses or opens those branches, says which it will do in its name and whether its branches show in
 *   aria-expanded, and lays the drawing out again the way the server did;
 *   Zoom in, Zoom out and Reset zoom scale the drawing inside its own scrolling frame, so the page never scrolls
 *   sideways.
 * Loaded under script-src 'self': no inline script, no handler attribute, no third-party library. Every data-*
 * attribute is read through dataset.
 */
(function () {
  'use strict';

  var STEP = 1.25;
  var MIN_SCALE = 0.25;
  var MAX_SCALE = 4;
  var FACTOR = { in: STEP, out: 1 / STEP };

  function num(el, name) { return Number(el.dataset[name]); }

  function zoom(svg, scale) {
    var s = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
    var width = num(svg, 'width');
    var height = num(svg, 'height');
    svg.dataset.scale = String(s);
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('width', String(width * s));
    svg.setAttribute('height', String(height * s));
  }

  function curve(from, to, boxW, boxH) {
    var x1 = from.x + boxW;
    var y1 = from.y + boxH / 2;
    var y2 = to.y + boxH / 2;
    var mid = (x1 + to.x) / 2;
    return 'M' + x1 + ' ' + y1 + ' C' + mid + ' ' + y1 + ' ' + mid + ' ' + y2 + ' ' + to.x + ' ' + y2;
  }

  /* tree_view.diagram's layout over the branches left showing: each leaf takes the next row, each branch sits midway
     between its first and last, and each turn takes a column. A branch under a collapsed one is hidden with its
     edge. */
  function layout(svg) {
    var margin = num(svg, 'margin');
    var boxW = num(svg, 'boxW');
    var boxH = num(svg, 'boxH');
    var colPitch = num(svg, 'colPitch');
    var rowPitch = num(svg, 'rowPitch');
    var boxes = Array.prototype.slice.call(svg.querySelectorAll('g.tree-dbox'));
    var children = {};
    boxes.forEach(function (box) {
      var parent = box.dataset.parent;
      (children[parent] = children[parent] || []).push(box);
    });
    var where = {};
    var rows = 0;
    function place(box, depth) {
      var shown = box.dataset.collapsed === 'true' ? [] : (children[box.dataset.key] || []);
      var ys = shown.map(function (child) { return place(child, depth + 1); });
      var y;
      if (ys.length) {
        y = (ys[0] + ys[ys.length - 1]) / 2;
      } else {
        y = margin + rows * rowPitch;
        rows += 1;
      }
      where[box.dataset.key] = { x: margin + depth * colPitch, y: y };
      return y;
    }
    (children[''] || []).forEach(function (root) { place(root, 0); });
    var edges = {};
    svg.querySelectorAll('path.tree-dedge').forEach(function (edge) { edges[edge.dataset.child] = edge; });
    boxes.forEach(function (box) {
      var at = where[box.dataset.key];
      var edge = edges[box.dataset.key];
      if (!at) {
        box.setAttribute('display', 'none');
        if (edge) { edge.setAttribute('display', 'none'); }
        return;
      }
      box.removeAttribute('display');
      box.setAttribute('transform', 'translate(' + at.x + ' ' + at.y + ')');
      if (edge) {
        edge.removeAttribute('display');
        edge.setAttribute('d', curve(where[box.dataset.parent], at, boxW, boxH));
      }
    });
    svg.dataset.height = String(2 * margin + (rows - 1) * rowPitch + boxH);
    zoom(svg, num(svg, 'scale'));
  }

  function show(toggle, open) {
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.setAttribute('aria-label', open ? toggle.dataset.collapseLabel : toggle.dataset.expandLabel);
    var plus = toggle.querySelector('.tree-dplus');
    if (!plus) { return; }
    if (open) {
      plus.setAttribute('display', 'none');
    } else {
      plus.removeAttribute('display');
    }
  }

  function flip(toggle) {
    var box = toggle.closest('g.tree-dbox');
    var open = box.dataset.collapsed === 'true';
    box.dataset.collapsed = open ? 'false' : 'true';
    show(toggle, open);
    layout(toggle.ownerSVGElement);
  }

  function within(event, selector) {
    var target = event.target;
    return target && target.closest ? target.closest(selector) : null;
  }

  SPECTRE.init('tree-diagram', function (figure) {
    var svg = figure.querySelector('svg');
    if (!svg) { return; }
    figure.querySelectorAll('g.tree-dtoggle').forEach(function (toggle) {
      toggle.removeAttribute('display');
      toggle.setAttribute('role', 'button');
      toggle.setAttribute('tabindex', '0');
      show(toggle, true);
    });
    figure.querySelectorAll('button.tree-zoom').forEach(function (button) { button.hidden = false; });
    figure.addEventListener('click', function (event) {
      var toggle = within(event, 'g.tree-dtoggle');
      if (toggle) {
        flip(toggle);
        return;
      }
      var button = within(event, 'button.tree-zoom');
      if (!button) { return; }
      var factor = FACTOR[button.dataset.zoom];
      zoom(svg, factor ? num(svg, 'scale') * factor : 1);
    });
    figure.addEventListener('keydown', function (event) {
      var toggle = within(event, 'g.tree-dtoggle');
      if (!toggle || (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar')) { return; }
      event.preventDefault();
      flip(toggle);
    });
  });
}());
