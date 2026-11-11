/* SPECTRE first-party script: the core every page loads (SPC-199, evaluation finding F-08).
 *
 * The console used to run on inline <script> blocks, inline onclick, onchange, oninput, onfocus and onkeydown
 * attributes, and hx-on attributes, which htmx 1.9.12 compiles with new Function. The Content Security Policy had
 * to carry 'unsafe-inline' and 'unsafe-eval' in script-src for them, so an injected handler would have run. Every
 * one of them is now a listener in a file under /static/js, and the policy carries neither keyword.
 *
 * How an element asks for behaviour, with no script in the markup:
 *   data-action="name"          a click runs the action registered as name, with (element, event)
 *   data-action-change="name"   a change event reaching the element runs the action
 *   data-action-input="name"    an input event reaching the element runs the action
 *   data-action-focus="name"    focus on the element itself runs the action
 *   data-activate               Enter or Space on the element itself clicks it (the keyboard path of a clickable
 *                               row or header; the old spectreActivate)
 *   data-init="name"            the init registered as name runs once on the element when it lands, on page load
 *                               or in an htmx swap (what an inline block in a fragment used to do)
 *   data-after-request="name"   htmx:afterRequest reaching the element runs the handler (what hx-on::after-request
 *                               used to do)
 *   data-after-settle="name"    htmx:afterSettle reaching the element runs the handler (hx-on::after-settle)
 *   hx-trigger="enterkey"       Enter released in the element fires its htmx request (the old keyup[key=='Enter'])
 *
 * Names resolve only against the registries below, never against window, so markup cannot call an arbitrary global.
 * A click runs the innermost element's action only, which is what every inline handler's stopPropagation was for.
 */
(function () {
  'use strict';

  var registries = {
    action: Object.create(null),
    init: Object.create(null),
    afterRequest: Object.create(null),
    afterSettle: Object.create(null)
  };

  function register(kind) {
    return function (name, fn) { registries[kind][name] = fn; };
  }

  var SPECTRE = {
    action: register('action'),
    init: register('init'),
    afterRequest: register('afterRequest'),
    afterSettle: register('afterSettle')
  };
  window.SPECTRE = SPECTRE;

  function holder(event, attr) {
    var target = event.target;
    return target && target.closest ? target.closest('[' + attr + ']') : null;
  }

  function dispatch(kind, attr) {
    return function (event) {
      var el = holder(event, attr);
      if (!el) { return; }
      var fn = registries[kind][el.getAttribute(attr)];
      if (fn) { fn(el, event); }
    };
  }

  document.addEventListener('click', dispatch('action', 'data-action'));
  document.addEventListener('change', dispatch('action', 'data-action-change'));
  document.addEventListener('input', dispatch('action', 'data-action-input'));
  document.addEventListener('htmx:afterRequest', dispatch('afterRequest', 'data-after-request'));
  document.addEventListener('htmx:afterSettle', dispatch('afterSettle', 'data-after-settle'));

  /* focus does not bubble and an onfocus attribute answered to its own element only, so focusin is read for the
     element itself, not an ancestor. */
  document.addEventListener('focusin', function (event) {
    var el = event.target;
    if (!el || !el.getAttribute) { return; }
    var fn = registries.action[el.getAttribute('data-action-focus')];
    if (fn) { fn(el, event); }
  });

  /* Keyboard equivalent for the sortable headers and expandable rows. A header or row that only answers to a click
     is unreachable without a mouse, which is a real barrier in an operations room where a console may be driven
     from the keyboard. Only when the opted-in element itself has focus: keydown bubbles, and a key press on a control
     nested in an activatable row must reach that control, not click the row. Space is included because a control
     that behaves like a button must answer to both keys, and its default scroll is suppressed. */
  document.addEventListener('keydown', function (event) {
    var el = event.target;
    if (!el || !el.hasAttribute || !el.hasAttribute('data-activate')) { return; }
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault();
      el.click();
    }
  });

  /* hx-trigger="keyup[key=='Enter']" was a filter htmx compiles with Function; this fires a plain event instead. */
  document.addEventListener('keyup', function (event) {
    var el = event.target;
    if (event.key === 'Enter' && el && el.matches && el.matches('[hx-trigger~="enterkey"]')) {
      window.htmx.trigger(el, 'enterkey');
    }
  });

  /* A form that clears once its own htmx request succeeded, as hx-on::after-request="this.reset()" did. */
  SPECTRE.afterRequest('resetOnSuccess', function (form, event) {
    if (event.detail.successful) { form.reset(); }
  });

  function runInits(root) {
    var found = [];
    if (root.matches && root.matches('[data-init]')) { found.push(root); }
    if (root.querySelectorAll) {
      Array.prototype.push.apply(found, root.querySelectorAll('[data-init]'));
    }
    found.forEach(function (el) {
      if (el.spectreInitDone) { return; }
      el.spectreInitDone = true;
      var fn = registries.init[el.getAttribute('data-init')];
      if (fn) { fn(el); }
    });
  }

  /* htmx raises htmx:load on the body once the page is parsed and on every fragment it swaps in, so an init runs
     for markup the server rendered into the page and for markup that arrives later, once each. */
  window.htmx.onLoad(runInits);
}());
