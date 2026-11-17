/* SPECTRE first-party script: training mode (SPC-199).
 *
 * Moved from the inline block in templates/training.html and the one in partials/training_scenario_active.html,
 * and the handlers and hx-on attributes on the training controls. The countdown's length comes from its marker's
 * data-remaining-s, where Jinja used to write it into the script.
 */

/* The console frame loads the console by name, so the console knows it is inside training: it then hides its own
   Training link and does not clean up after training as a console opened directly does (routes/training.py). */
var TRAINING_CONSOLE_URL = '/?frame=training';

/* Whether the frame shows planning lists or a scenario time that have since changed. A scenario start, reset, abandon
   or submission raises training-console-stale (routes/training.py), and the frame then reloads when the Console tab
   is next shown, or at once if it is showing. It used to load once and keep showing the first scenario's lists
   (audit F0). Opening the tab with nothing changed keeps the frame as it was, so work in it is not lost. */
var trainingConsoleStale = true;

function loadTrainingConsole() {
  var frame = document.getElementById('training-console-frame');
  if (!frame) return;
  frame.src = TRAINING_CONSOLE_URL;
  trainingConsoleStale = false;
}

function trainingConsoleShowing() {
  var panel = document.getElementById('tpanel-console');
  return Boolean(panel) && panel.style.display === 'block';
}

document.addEventListener('training-console-stale', function () {
  trainingConsoleStale = true;
  if (trainingConsoleShowing()) loadTrainingConsole();
});

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
    if (trainingConsoleStale) loadTrainingConsole();
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
SPECTRE.afterRequest('scrollScenarioDetail', function () { setTimeout(scrollScenarioDetail, 100); });

/* ── A scenario attempt: the objectives ticked, and the countdown ── */
function updateObjectivesJson() {
  var checked = Array.from(
    document.querySelectorAll('#scenario-submit-form input[type=checkbox]:checked')
  ).map(function(cb) { return cb.value; });
  document.getElementById('objectives-json').value = JSON.stringify(checked);
}
SPECTRE.action('updateObjectivesJson', function () { updateObjectivesJson(); });

/* Typing an answer, or choosing a verdict, ticks its objective: an answer typed under an unticked box used to score
   nothing (audit 3-3). Clearing the answer leaves the box as it is. */
SPECTRE.action('answerTicksObjective', function (field) {
  if (!field.value.trim()) return;
  var box = document.getElementById('obj-box-' + field.dataset.objective);
  if (box && !box.checked) {
    box.checked = true;
    updateObjectivesJson();
  }
});

SPECTRE.init('scenario-attempt', function (marker) {
  if (marker.dataset.remainingS === undefined) return;
  var remaining = Number(marker.dataset.remainingS);
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
