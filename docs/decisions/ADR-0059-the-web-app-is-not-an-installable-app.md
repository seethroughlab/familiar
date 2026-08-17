# ADR-0059: The Web App Is Not an Installable App

Status: accepted

Date: 2026-08-17

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md). That said what the browser
*is*. This removes the last thing it still claimed to be.

## Context

The web app shipped as a Progressive Web App: a manifest, `apple-mobile-web-app-*` meta tags, a
Workbox service worker precaching the shell, runtime caches for artwork and API responses, and an
`InstallPrompt` that appeared over the interface encouraging people to install it to their home
screen.

**Every premise of that has been reversed, one ADR at a time.** `ADR-0001` made native Apple clients
the listening path. `ADR-0013` made macOS a management surface. `ADR-0050` reduced the browser to
management. `ADR-0057` gave that a rule. `ADR-0058` made it an administration tool that opens on a
library dashboard. The marketing site was rewritten to stop referring to the PWA for playback at
all.

Nobody removed the PWA itself. So the administration page for a music server was still asking to be
installed to a phone's home screen — a phone that, if it belongs to this user, is running the native
app the same page's `MobileAppRedirect` points at.

**A second, quieter problem.** `InstallStatus` — the same component's other export — was on the
Server destination, filling the "update channel" slot `ADR-0058` point 2 named. It reported PWA
install state. It was never an update channel; nothing has ever been.

**The offline story belongs to the player, not the shell.** Downloaded tracks live in IndexedDB via
Dexie. The service worker cached the *app shell* and API responses. Losing it means the
administration tool no longer loads without a server — which is the correct behaviour for a tool
whose entire subject is that server, and which `ADR-0058` point 5 already schedules the offline
settings to leave with the player.

**The trap this ADR exists to handle.** Deleting a service worker does not remove it. A browser that
registered `/sw.js` keeps running the installed Workbox worker, which serves the shell **cache
first** — so it keeps serving the old `index.html` and the old bundle indefinitely. Unregistration
code added to `main.tsx` never executes, because the code that runs is the cached code that predates
it. Removing the file does not help; nothing would be left to notice. This is the one part of the
change that cannot be got wrong quietly, because the symptom is "the app never updates again" on
machines nobody is testing.

## Decision

1. **The web app is a plain web page.** No manifest, no service worker, no install affordance, no
   `apple-mobile-web-app-*` meta tags. It administers a server; it is not something you install.

2. **`InstallPrompt` and `InstallStatus` are deleted, and the `vite-plugin-pwa` dependency with
   them.** Both exports had exactly one call site each and neither has a replacement, because
   neither described anything that still exists.

3. **`/sw.js` keeps being served, and serves a tombstone.** A worker whose only behaviour is to
   claim its clients, delete every cache, unregister itself, and reload open tabs. This is the
   mechanism that recovers an existing install: the browser re-fetches the worker URL on navigation,
   byte-compares, and installs the difference. **It must not 404** — that falls through to the SPA
   catch-all and answers with `index.html`.

4. **The tombstone is deleted only when no browser that installed the old worker will be opened
   again**, which is not a date anyone can name. It costs a few hundred bytes and it is commented
   with why it exists, because its natural reading is "dead file".

5. **`isPWA()` goes.** Its single caller suppressed the iPhone App Store hand-off when already
   running installed. There is no installed copy to be inside.

6. **The App Store hand-off stays and is the point.** `MobileAppRedirect` and the
   `apple-itunes-app` Smart App Banner send an iPhone visitor to the real listening client, which is
   what `ADR-0050` says the phone should be using. Retiring the PWA is not retiring mobile — it is
   sending mobile somewhere better.

7. **Playwright keeps `serviceWorkers: 'block'`.** There is no longer a worker to swallow a mocked
   GET, but the setting is what stops that class of bug returning, and it cost seven specs once
   already.

## Alternatives Considered

- **Remove only the install prompt.** What was actually asked for, and the smallest change. Rejected
  because the prompt is the visible tip: the manifest, the meta tags, the worker and the runtime
  caches would remain, and the next person would find an app that is still a PWA in every respect
  except that it no longer says so. The install prompt is not the feature; it is the advertisement.

- **Keep the service worker for offline shell loading.** Genuinely arguable — a cached shell means
  the administration page opens on a flaky connection, and downloaded tracks stay reachable in the
  fallback player without a network round trip for the HTML. Rejected because an administration tool
  that loads while its server is unreachable can do nothing except show stale numbers, and
  ADR-0058 point 6 is specifically about not showing numbers that are not backed by a live query.
  The cost is named rather than argued away: **a browser-only listener loses offline access to
  tracks they already downloaded**, because the shell will not load.

- **Delete `/sw.js` outright and let it 404.** Tidier, and tempting. Rejected on the mechanics: the
  route falls through to the SPA catch-all, so the browser is handed `index.html` as its service
  worker — behaviour that varies by engine, where a script that removes itself does not.

- **Ship the tombstone and delete it in a month.** Rejected because "a month" is a guess about
  machines we cannot enumerate. A guest laptop opened twice a year is exactly the case that breaks,
  and the file is a few hundred bytes.

## Consequences

- **Positive:** the install popup is gone, and with it the last thing telling a person this page is
  an app for their phone.
- **Positive:** one fewer build dependency (`vite-plugin-pwa` and Workbox), and one fewer caching
  layer between a deploy and what a browser shows — which has already cost real debugging time in
  the E2E suite, where Workbox's runtime caching silently served mocked GETs from the real backend.
- **Tradeoff:** the administration tool no longer opens offline, and a browser-only listener loses
  offline access to downloaded tracks. Accepted; the tracks themselves are untouched in IndexedDB,
  and ADR-0058 point 5 already schedules offline settings to leave with the player.
- **Tradeoff:** a tombstone file that looks like dead code has to survive future cleanups. Mitigated
  by point 4 and by the comment in the file, not by hoping.
- **Follow-up:** ~~`isNativeApp()` tests for `window.Capacitor`, and the Capacitor app was deleted on
  2026-08-11~~ — done. [ADR-0060](ADR-0060-the-players-removal-trigger-must-be-reachable.md) shipped
  the removal alongside its own subject: `isNativeApp`, the Connect-to-Server screen,
  `ServerSettings`, `AirPlayButton` and its unregistered bridge, the preferences provider, the
  filesystem layer in `offlineService`/`prefetchService`, `isCapacitorNative` and the
  `BUILD_TARGET=capacitor` variant. Same shape as this ADR — a platform layer outliving its
  platform.
