/* The install section's two choosers (ADR-0143): where the server runs, and where you listen.
 *
 * `site/` has no build step, so this is a plain script, loaded with `defer`.
 *
 * **It only ever hides.** ADR-0095 point 6, kept by ADR-0143: with the script absent, blocked or
 * broken, every panel is in the document and visible under its own heading, and the page still
 * says everything it needs to. The tab strips are `display: none` until this runs, so nobody is
 * offered a control that cannot do anything — the defect this project keeps producing is an
 * affordance whose destination is not mounted.
 *
 * The chosen pair lives in the URL, `#install?server=mac&client=iphone`, so a link sent to someone
 * lands on their path. An unknown value is ignored, not an error. The URL is only written once the
 * reader chooses, so arriving at the page never rewrites it.
 *
 * Deliberately no platform detection. `navigator.platform` describes the machine reading the page,
 * and the likely reader is on a phone planning a server somewhere else.
 */
(function () {
  'use strict';

  var choosers = {};
  var strips = document.querySelectorAll('[data-chooser]');
  for (var s = 0; s < strips.length; s++) {
    var strip = strips[s];
    var tabs = Array.prototype.slice.call(strip.querySelectorAll('[role="tab"]'));
    var panels = tabs.map(function (t) { return document.getElementById(t.getAttribute('data-panel')); });
    if (!tabs.length || panels.indexOf(null) !== -1) return; // a half-wired chooser: show everything
    choosers[strip.getAttribute('data-chooser')] = { tabs: tabs, chosen: null };
  }
  if (!choosers.server || !choosers.client) return;

  function select(name, tab, focus) {
    var chooser = choosers[name];
    chooser.chosen = tab.getAttribute('data-value');
    chooser.tabs.forEach(function (t) {
      var chosen = t === tab;
      t.setAttribute('aria-selected', chosen ? 'true' : 'false');
      // Roving tabindex: each strip is one stop in the tab order, arrows move within it.
      t.setAttribute('tabindex', chosen ? '0' : '-1');
      document.getElementById(t.getAttribute('data-panel')).hidden = !chosen;
    });
    // Text that is true only for one server, such as "Open in Familiar" for Familiar Server on the
    // same Mac. Without this script it stays visible and says which server it is for.
    var conditional = document.querySelectorAll('.when-server');
    for (var i = 0; i < conditional.length; i++) {
      conditional[i].hidden = conditional[i].getAttribute('data-server') !== choosers.server.chosen;
    }
    // And the reverse: the memory note is about Docker machines, not Familiar Server.
    var unless = document.querySelectorAll('.unless-server');
    for (var j = 0; j < unless.length; j++) {
      unless[j].hidden = unless[j].getAttribute('data-server') === choosers.server.chosen;
    }
    if (focus) tab.focus();
  }

  function remember() {
    var hash = '#install?server=' + choosers.server.chosen + '&client=' + choosers.client.chosen;
    if (window.history && history.replaceState) history.replaceState(null, '', hash);
  }

  Object.keys(choosers).forEach(function (name) {
    var tabs = choosers[name].tabs;
    tabs.forEach(function (tab, i) {
      // Given here rather than in the HTML so that a page without this script has no ids pointing
      // at labels that do not exist.
      tab.id = 'tab-' + tab.getAttribute('data-panel');
      tab.addEventListener('click', function () { select(name, tab, false); remember(); });
      tab.addEventListener('keydown', function (event) {
        var next = null;
        if (event.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
        else if (event.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
        else if (event.key === 'Home') next = tabs[0];
        else if (event.key === 'End') next = tabs[tabs.length - 1];
        if (next) {
          event.preventDefault();
          select(name, next, true);
          remember();
        }
      });
    });
  });

  // Reveals the strips and collapses the stacked headings. Added here rather than in the markup, so
  // the no-JavaScript case is correct by default rather than by remembering.
  document.documentElement.classList.add('js-platforms');

  function follow() {
    var match = /^#install\?(.*)$/.exec(window.location.hash);
    var asked = {};
    if (match) {
      match[1].split('&').forEach(function (pair) {
        var kv = pair.split('=');
        asked[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
      });
    }
    Object.keys(choosers).forEach(function (name) {
      var tabs = choosers[name].tabs;
      var wanted = tabs.filter(function (t) { return t.getAttribute('data-value') === asked[name]; })[0];
      select(name, wanted || tabs[0], false);
    });
    // `#install?…` names no element, so the browser did not scroll to the section.
    if (match) document.getElementById('install').scrollIntoView();
  }

  follow();
  // A link to another path followed from this page changes only the fragment, so nothing reloads.
  // replaceState, which is how a choice is remembered, does not fire this.
  window.addEventListener('hashchange', follow);
})();
