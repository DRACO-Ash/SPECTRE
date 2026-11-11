/* SPECTRE first-party script: training mode (SPC-199).
 *
 * Moved from the inline block in templates/training.html and the one in partials/training_scenario_active.html,
 * and the handlers and hx-on attributes on the training controls. The countdown's length comes from its marker's
 * data-remaining-s, where Jinja used to write it into the script.
 */

function trainingTab(id) {
  var isConsole = id === 'console';
  var main = document.getElementById('training-main');

  document.querySelectorAll('.training-panel').forEach(function(p) {
    p.style.display = 'none';
  });
  var panel = document.getElementById('tpanel-' + id);
  if (panel) panel.style.display = 'block';

  // Console tab: make main a positioned container so the panel fills it absolutely
  if (isConsole) {
    main.style.overflow = 'hidden';
    main.style.padding  = '0';
    main.style.position = 'relative';
    // Lazy-load iframe: only set src once
    var frame = document.getElementById('training-console-frame');
    if (frame && !frame.dataset.loaded) {
      frame.src = '/';
      frame.dataset.loaded = '1';
    }
  } else {
    main.style.overflow = 'auto';
    main.style.padding  = '0.75rem';
    main.style.position = '';
  }

  document.querySelectorAll('.training-nav-btn').forEach(function(btn) {
    var active = btn.id === 'tnav-' + id;
    btn.style.background    = active ? 'rgba(245,158,11,0.15)' : 'transparent';
    btn.style.borderColor   = active ? 'rgba(245,158,11,0.4)'  : 'transparent';
    btn.style.color         = active ? '#f59e0b'               : 'var(--text-dim)';
  });
}

function scrollScenarioDetail() {
  var el = document.getElementById('scenario-detail');
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* A tab button names its tab in data-tab, and data-scroll-to the element to bring into view after it. */
SPECTRE.action('trainingTab', function (btn) {
  trainingTab(btn.dataset.tab);
  if (btn.dataset.scrollTo) {
    document.getElementById(btn.dataset.scrollTo).scrollIntoView({ behavior: 'smooth' });
  }
});
SPECTRE.action('scrollTo', function (btn) {
  document.getElementById(btn.dataset.scrollTo).scrollIntoView({ behavior: 'smooth' });
});
SPECTRE.action('loadFirstScenario', function (btn) {
  trainingTab('scenarios');
  htmx.ajax('GET', btn.dataset.scenarioUrl, { target: '#scenario-detail', swap: 'innerHTML' });
  setTimeout(scrollScenarioDetail, 300);
});
SPECTRE.action('clearScenarioDetail', function () {
  document.getElementById('scenario-detail').innerHTML = '';
});
SPECTRE.afterRequest('scrollScenarioDetail', function () { setTimeout(scrollScenarioDetail, 100); });

/* ── A scenario attempt: the objectives ticked, and the countdown ── */
function updateObjectivesJson() {
  var checked = Array.from(
    document.querySelectorAll('#scenario-submit-form input[type=checkbox]:checked')
  ).map(function(cb) { return cb.value; });
  document.getElementById('objectives-json').value = JSON.stringify(checked);
}
SPECTRE.action('updateObjectivesJson', function () { updateObjectivesJson(); });

SPECTRE.init('scenario-attempt', function (marker) {
  if (!marker.hasAttribute('data-remaining-s')) return;
  var remaining = Number(marker.getAttribute('data-remaining-s'));
  var form = document.getElementById('scenario-submit-form');
  var timerInterval = setInterval(function() {
    var display = document.getElementById('timer-display');
    /* Stopped once the attempt's panel is gone (Abandon, Reset or a new scenario): the inline countdown kept
       running and threw on the missing display every second. */
    if (!display || !document.contains(form)) { clearInterval(timerInterval); return; }
    remaining--;
    if (remaining < 0) {
      clearInterval(timerInterval);
      display.textContent = '0:00';
      return;
    }
    var m = Math.floor(remaining / 60);
    var s = remaining % 60;
    display.textContent = m + ':' + (s < 10 ? '0' : '') + s;
    if (remaining < 120) display.style.color = '#ef4444';
  }, 1000);
  // The countdown is a display only: the server measures the elapsed time
  // from when the attempt started and judges the time limit itself.
  if (form) {
    form.addEventListener('submit', function() { clearInterval(timerInterval); });
  }
});
