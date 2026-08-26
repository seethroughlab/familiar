# ADR-0080: The Web App Is Navigated from a Top Bar

Status: accepted

Date: 2026-08-18

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md), which established the three
destinations. This decides the chrome that reaches them, and what the shell stops mounting. It also
**replaces `ADR-0058` point 5's "Theme outlives both" clause** — see point 7.

## Context

**The sidebar is not the problem, and it is worth saying so before replacing it.**
`components/Sidebar/Sidebar.tsx` is 157 lines, built for `ADR-0058`'s three destinations: it maps
`DESTINATIONS` to icons, offers a 56px collapsed rail and a 240px expanded one, and carries no player
affordance — no search, no collections, no now-playing. It is not a remnant.

**The shell around it was, and most of that has already gone.** When this ADR was proposed,
`components/AppShell.tsx` was 263 lines mounting a `PlayerBar`, a queue/session right panel, full-player
and ambient overlays, mobile overlays and a `HomeRouteTracker`, while `hooks/useAppBootstrap.ts` built
an audio engine, a scrobbler and a play tracker on every page load and `hooks/useKeyboardShortcuts.ts`
bound Space, arrows, volume, mute, shuffle and repeat globally.

**That is no longer the state of the file, and the Decision below is amended rather than left to
describe an app that has moved.** `AppShell.tsx` is 77 lines at the time of acceptance; `PlayerBar`,
`useAppBootstrap` and `useKeyboardShortcuts` do not exist in the repo at all. They left with the
fallback player under `ADR-0070` and `ADR-0071`. What point 2 still has to decide is the small part
that remained.

So the question is not whether the rail is a leftover. It is that a 240px vertical rail is a large
amount of chrome for three destinations, and it exists in that form because it replaced something
that needed it.

**Three further findings came out of building it**, and they turn what was a navigation change into
a mostly subtractive one:

- **`ContentToolbar.tsx` (133 lines) is dead chrome.** Its search box and column chooser render only
  when `pathname.startsWith('/library/')`, and the one mounted `/library/*` route is
  `artist-cleanup`, which reads neither the `search` parameter nor `columnStore`. On the three
  destinations it renders a bordered strip containing nothing but the status menu.
- **`/settings` holds exactly one control.** `components/Settings/index.tsx` renders only
  `<ThemeSettings />`; `ADR-0058` point 2 moved everything else onto Library, Tools and Server, and
  point 5 deleted the listener preferences. A destination whose entire content is a theme picker is
  not a destination.
- **Light mode never worked, and could not have.** There is no `tailwind.config.js` in the repo and
  no `@custom-variant light` in `packages/frontend/src/index.css`, so **all 78 `light:` utility
  classes compiled to nothing**. Only six files branched on `resolvedTheme` in JavaScript, so
  selecting light flipped a handful of backgrounds to white while `text-white` stayed everywhere
  else. The reported symptom — "light mode hides all of the text" — is the whole feature working as
  built. The 76 `dark:` classes beside them were equally inert in a useful sense: every one duplicated
  a bare utility already present on the same element.

## Decision

1. **One top bar carries navigation, at every viewport.** Product name and the three `ADR-0058`
   destinations, as icon-above-label links. No sidebar, no collapse control, no mobile bottom nav,
   no "More" sheet. Three destinations fit across a phone, and the interface is responsive rather
   than two interfaces.

2. **`AppShell` mounts only what an administration tool needs**: the top bar, the routed outlet, an
   error boundary, the offline indicator and the two modals a screen can open. `ContentToolbar` is
   deleted with the sidebar, and `Library/ColumnSelector.tsx` with it — the toolbar was its only
   consumer. Most of what this point originally listed had already left with the player; what is
   left of it is this.

3. **The destinations are links with accessible names matching their labels.**
   `packages/web/e2e/helpers.ts` finds them by `getByRole('link', { name: label, exact: true })`,
   so the existing end-to-end helper keeps working unmodified across the redesign — and its mobile
   fallback branch stops being needed. Preserving a test seam is a cheaper way to prove a redesign
   did not break navigation than rewriting the tests that would have proved it.

4. **`navigationIntegrity`'s source scan reads every component, not a list of files.** It read
   exactly three — `Sidebar.tsx`, `LibraryPage.tsx`, `ToolsPage.tsx` — which is why a dead affordance
   survived in a file it did not read: `StatusMenu.tsx:283` navigated to `/library/proposed-changes`,
   which is unmounted and silently redirects home. **A hand-maintained list of files to check is the
   same shape of mistake as the bug it is checking for**, so the scan now walks `components/`
   recursively and asserts every `to="/…"` and `navigate('/…')` in it resolves to a mounted route.

5. **Dead affordances are fixed rather than carried across.** `ADR-0057` point 5 applies — the
   affordance leaves with the capability it cannot reach. Removed: the status menu's proposed-changes
   link (the Mac owns that surface under `ADR-0013`); `MobileMoreSheet`'s `/library/tracks` entry and
   its Settings button, which set `uiStore.showSettings` for no reader; and `useAppNavigation`'s
   `navigateToFavorites` and `navigateToDownloads`, which had no callers and pointed at routes
   deleted by `ADR-0057`.

6. **The status menu is removed, and the one thing it alone carried moves to Server.** Of its four
   sections, three had somewhere else to be: health is polled by `WorkerAlert` and reported by
   `SystemStatus`, mix-tape renders are watched by `MixTapeProgressWatcher` and listed by
   `MixTapesList`, and the proposed-changes link went under point 5. **Background jobs did not.**
   `library_sync` has its own progress on the Library dashboard, but `artwork_fetch` and `s3_backup`
   had no indicator anywhere else, so they become a `Jobs` section on Server that is absent when
   nothing is running. Deleting an always-mounted status affordance is only safe once you have
   checked what it was quietly hosting.

7. **The administration interface is dark only, and the theme mechanism is deleted** — picker,
   store, CSS `.light` block and all 78 `light:` classes, along with the 76 `dark:` duplicates.
   `ADR-0058` point 5 said theme outlives the player "because it applies to this administration
   interface itself"; that reasoning assumed a working light theme, and there has never been one.
   **`/settings` goes with it**, having no other content, and its URL falls through the catch-all to
   the dashboard.

8. **Nothing in the shell constructs an audio engine.** This is the property `ADR-0017` gives the
   embedded surfaces by using a separate entry point, and the reason `renderEmbed.tsx` exists rather
   than the app with its chrome hidden — *"hiding is not preventing"*. The administration tool now
   makes the same guarantee for the same reason.

## Alternatives Considered

**Keep a rail, rebuilt.** A 56px icon rail is conventional for an administration console and leaves
room for a fourth destination. Rejected because the cost is paid on every screen for an affordance
used a handful of times per session, and because a vertical rail is the strongest single visual cue
that this application is shaped like a media library browser.

**No persistent navigation — dashboard as home, everything reached from its tiles.** The strongest
"this is a dashboard" signal, and genuinely considered. Rejected because every destination would cost
a trip through home, and `ADR-0058` point 1 already makes the dashboard the landing page; adding a
mandatory return to it converts one click into two for no gain.

**Keep the sidebar and only strip the shell.** This is the smaller change, and it would remove the
player bar, the overlays and the audio engine — most of the actual benefit. Rejected because the
question was asked directly and answered: with three destinations, the rail is more chrome than the
navigation needs. It has also since been overtaken: that strip happened under `ADR-0070`/`ADR-0071`,
and doing it again is not an available option.

**Different chrome per viewport, as today** — sidebar on desktop, bottom nav plus sheet on mobile.
Rejected as the source of two of the defects in point 5: the mobile-only components are the ones the
navigation test does not read and nobody opens, which is exactly where a dead affordance survives.

**Fix light mode instead of deleting it** — register a `light` variant so the 78 classes activate,
and keep the picker. Rejected because activating them is the cheap half: every screen would then need
auditing against a palette no one has ever seen rendered, to support a second look in a single-operator
tool. The classes are evidence of intent, not of a working feature.

**Keep the status menu and only move it into the top bar**, as this ADR originally proposed.
Rejected on use: it renders nothing unless something is active, so in normal operation it is an empty
slot, and the one category with no other home is better read on the page that owns the server.

## Consequences

- **Positive** — one navigation implementation replaces three (`Sidebar`, `MobileBottomNav`,
  `MobileMoreSheet`), and the one that remains is the one covered by tests.
- **Positive** — four live dead-affordance defects are fixed, and the check that would have caught
  them stops depending on somebody remembering to add a file to a list.
- **Positive** — the interface has one appearance, which is one fewer axis for a screen to be broken
  along. `uiStore` loses its `persist` wrapper and the `familiar-ui` localStorage key with it, since
  `sidebarCollapsed` was the only thing it kept.
- **Tradeoff** — horizontal space is finite. Three destinations fit comfortably; a fourth or fifth
  would push toward an overflow control, which is the failure mode a rail does not have.
- **Tradeoff** — `Sidebar.tsx` is deleted despite being recently built and fit for its purpose. That
  is a real cost and it is being paid for the shape of the product rather than for a defect in the
  component.
- **Tradeoff** — dark only is a decision made for a single-operator tool on a tailnet. If this
  interface ever has users who did not choose it, it has to be revisited, and the deleted `light:`
  classes are not a starting point worth restoring.
- **Follow-up** — `hooks/useAppNavigation.ts` is mostly dead: after point 5, six of its eight
  remaining helpers have no caller and navigate to `/library/tracks` or `/smart-playlists/:id`,
  neither mounted. Only `navigateToArtist` and `navigateToAlbum` are called, from
  `useTrackContextMenu`, which is on the embed path. Not cleaned up here because unpicking it reaches
  into code the Apple clients render.
- **Follow-up** — `components/TrackEdit/` (2,115 lines) is mounted by the shell today. Whether the
  administration tool still edits track metadata is a genuine question this ADR does not answer; it
  is kept mounted only if a screen opens it.

## Implementation

Shipped on `admin/top-bar-navigation`. `components/TopBar.tsx` replaces `Sidebar/`, `ContentToolbar.tsx`,
`MobileNav/` and `StatusMenu.tsx`; `Settings/BackgroundJobs.tsx` carries point 6 onto `Admin/ServerPage.tsx`;
`stores/themeStore.ts`, `Settings/ThemeSettings.tsx`, `Settings/index.tsx` and `Library/ColumnSelector.tsx`
are deleted along with the `/settings` route.

- **Point 4 was verified by making it fail.** A component linking to `/library/proposed-changes` —
  the exact affordance the old scan missed — was added, the test named the file and the target, and
  it was removed again. A guard that has never been seen failing is a guard nobody has checked.
- **`uiStore` shrank from eight fields to one.** `rightPanel`, `showFullPlayer` and
  `showAmbientScreen` turned out to have lost their last readers when the player went; `showFullPlayer`
  lost its final one — `MobileBottomNav` — to point 1. Only the playlist picker's state is still read.
