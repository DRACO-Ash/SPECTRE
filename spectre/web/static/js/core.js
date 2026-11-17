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

  /* The console in the training page's frame serves every request from the sign-in's training planning state, and
     the server knows a request comes from the frame by its X-Spectre-Frame header (spectre/web/training_frame.py).
     htmx sends it from the body's hx-headers; this adds it to every same-origin fetch() the page's scripts make
     (operator.js, pol.js), so none of them reads or writes the operational state (0.47.0 review B1). */
  function frameFetch(plainFetch) {
    return function (resource, init) {
      var url = new URL(String(resource instanceof Request ? resource.url : resource), window.location.href);
      if (url.origin !== window.location.origin) { return plainFetch(resource, init); }
      var options = Object.assign({}, init);
      var headers = new Headers(options.headers || (resource instanceof Request ? resource.headers : undefined));
      headers.set('X-Spectre-Frame', 'training');
      options.headers = headers;
      return plainFetch(resource, options);
    };
  }
  /* XMLHttpRequest too, which htmx and any other script use (review N1): every same-origin request opened on the
     page carries the header once. htmx also sends it from hx-headers; the second setting is skipped, as XHR would
     otherwise join the two into "training, training". */
  function sameOrigin(url) {
    return new URL(String(url), window.location.href).origin === window.location.origin;
  }
  function frameXhr(proto) {
    var plainOpen = proto.open;
    var plainSet = proto.setRequestHeader;
    proto.open = function (method, url) {
      plainOpen.apply(this, arguments);
      this.spectreFrameSent = sameOrigin(url);
      if (this.spectreFrameSent) { plainSet.call(this, 'X-Spectre-Frame', 'training'); }
    };
    proto.setRequestHeader = function (name, value) {
      if (this.spectreFrameSent && String(name).toLowerCase() === 'x-spectre-frame') { return; }
      plainSet.call(this, name, value);
    };
  }
  if (document.body && document.body.dataset.spectreFrame === 'training') {
    if (window.fetch) { window.fetch = frameFetch(window.fetch.bind(window)); }
    frameXhr(window.XMLHttpRequest.prototype);
  }

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
    if (!el || !el.dataset) { return; }
    var fn = registries.action[el.dataset.actionFocus];
    if (fn) { fn(el, event); }
  });

  /* Keyboard equivalent for the sortable headers and expandable rows. A header or row that only answers to a click
     is unreachable without a mouse, which is a real barrier in an operations room where a console may be driven
     from the keyboard. Only when the opted-in element itself has focus: keydown bubbles, and a key press on a control
     nested in an activatable row must reach that control, not click the row. Space is included because a control
     that behaves like a button must answer to both keys, and its default scroll is suppressed. */
  document.addEventListener('keydown', function (event) {
    var el = event.target;
    if (!el || !el.dataset || el.dataset.activate === undefined) { return; }
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
      var fn = registries.init[el.dataset.init];
      if (fn) { fn(el); }
    });
  }

  /* htmx raises htmx:load on the body once the page is parsed and on every fragment it swaps in, so an init runs
     for markup the server rendered into the page and for markup that arrives later, once each. */
  window.htmx.onLoad(runInits);
}());
