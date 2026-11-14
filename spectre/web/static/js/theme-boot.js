/* SPECTRE first-party script: applied before first paint (SPC-199).
 *
 * Loaded without defer in <head>, as the inline block it replaces ran, so the saved theme is set before the page
 * paints and the console does not flash the default theme. It also marks the page when the splash has been seen
 * this session, so the stylesheet hides the splash before it paints; the inline splash block used to remove it
 * synchronously, mid-parse.
 */
(function () {
  var root = document.documentElement;
  try {
    var t = localStorage.getItem('spectre-theme');
    var valid = ['ops', 'steel'];
    if (t && valid.includes(t)) {
      root.dataset.theme = t;
      root.dataset.spectreTheme = t === 'steel' ? 'light' : 'dark';
    } else if (t) {
      localStorage.removeItem('spectre-theme');
    }
  } catch (_) { /* storage refused: the default theme stands */ }
  try {
    if (sessionStorage.getItem('spectre-splash-seen')) { root.classList.add('spectre-splash-seen'); }
  } catch (_) { /* storage refused: the splash shows */ }
}());
