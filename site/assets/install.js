/* The install section's platform chooser (ADR-0095 point 2).
 *
 * The site's first JavaScript. `site/` has no build step — ADR-0069 would add Eleventy and is
 * proposed and unstarted — so this is a plain script, loaded with `defer`, doing one thing.
 *
 * **It only ever hides.** Point 6: with the script absent, blocked or broken, all four panels are
 * in the document and visible, each under its own heading, and the page still says everything it
 * needs to. The tab strip is `display: none` until this runs, so nobody is offered a control that
 * cannot do anything — the defect this project keeps producing is an affordance whose destination
 * is not mounted.
 *
 * Deliberately no platform detection. `navigator.platform` describes the machine reading the page,
 * and the likely reader is on a phone planning to install on a NAS in a cupboard; auto-selecting
 * would show them the wrong panel with confidence.
 */
(function () {
  'use strict';

  var root = document.getElementById('platforms');
  if (!root) return;

  var tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tab"]'));
  var panels = Array.prototype.slice.call(root.querySelectorAll('.platform-panel'));
  if (!tabs.length || tabs.length !== panels.length) return;

  function select(tab, focus) {
    tabs.forEach(function (t) {
      var chosen = t === tab;
      t.setAttribute('aria-selected', chosen ? 'true' : 'false');
      // Roving tabindex: the strip is one stop in the tab order, arrows move within it.
      t.setAttribute('tabindex', chosen ? '0' : '-1');
      var panel = document.getElementById(t.getAttribute('data-panel'));
      if (panel) panel.hidden = !chosen;
    });
    if (focus) tab.focus();
  }

  tabs.forEach(function (tab, i) {
    // Given here rather than in the HTML so that a page without this script has no ids pointing at
    // labels that do not exist.
    tab.id = 'tab-' + tab.getAttribute('data-panel');
    tab.addEventListener('click', function () { select(tab, false); });
    tab.addEventListener('keydown', function (event) {
      var next = null;
      if (event.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
      else if (event.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
      else if (event.key === 'Home') next = tabs[0];
      else if (event.key === 'End') next = tabs[tabs.length - 1];
      if (next) {
        event.preventDefault();
        select(next, true);
      }
    });
  });

  // Reveals the strip and collapses the stacked headings. Adding it here rather than in the markup
  // is what makes the no-JavaScript case correct by default rather than by remembering.
  document.documentElement.classList.add('js-platforms');
  select(tabs[0], false);
})();
