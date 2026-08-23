# ADR-0080: The Web App Is Navigated from a Top Bar

Status: proposed

Date: 2026-08-18

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md), which established the three
destinations. This decides the chrome that reaches them, and what the shell stops mounting.

## Context

**The sidebar is not the problem, and it is worth saying so before replacing it.**
`components/Sidebar/Sidebar.tsx` is 157 lines, built for `ADR-0058`'s three destinations: it maps
`DESTINATIONS` to icons, offers a 56px collapsed rail and a 240px expanded one, and carries no player
affordance — no search, no collections, no now-playing. It is not a remnant.

**The shell around it is.** `components/AppShell.tsx` is 263 lines and mounts, on every
administration page:

| | |
|---|---|
| `PlayerBar` (512 lines), full width, bottom, always | renders "No track selected" to an administrator who never plays anything |
| a 320px Queue / Listening Session right panel | |
| `FullPlayer` and `AmbientScreen` overlays | lazy, kept mounted after first open |
| mobile Queue and Listening Session overlays | |
| `TrackEditModal` (2,115 lines behind it), `PlaylistPickerModal` | |
| `HomeRouteTracker` | records recent destinations for a Home screen nothing can reach |

and `hooks/useAppBootstrap.ts:36-38` constructs the **audio engine**, scrobbling and play-tracking on
every page load, while `hooks/useKeyboardShortcuts.ts` binds Space, arrows, volume, mute, shuffle and
repeat globally — in a tool whose job is scanning a library and reading server health.

So the question is not whether the rail is a leftover. It is that a 240px vertical rail is a large
amount of chrome for three destinations, and it exists in that form because it replaced something
that needed it.

## Decision

1. **One top bar carries navigation, at every viewport.** Product name, the three `ADR-0058`
   destinations, the status menu and settings. No sidebar, no collapse control, no mobile bottom nav,
   no "More" sheet. Three destinations and a gear fit across a phone.

2. **`AppShell` becomes `AdminShell`, and mounts only what an administration tool needs**: the top
   bar, the routed outlet, an error boundary, the offline indicator, the toaster, and the mix-tape
   progress watcher. **No `useAppBootstrap`, no `useKeyboardShortcuts`, no audio engine, no player
   bar, no queue panel, no overlays.**

3. **The destinations are links with accessible names matching their labels.**
   `packages/web/e2e/helpers.ts:124` finds them by `getByRole('link', { name: label, exact: true })`,
   so the existing end-to-end helper keeps working unmodified across the redesign — and its mobile
   fallback branch stops being needed. Preserving a test seam is a cheaper way to prove a redesign
   did not break navigation than rewriting the tests that would have proved it.

4. **`navigationIntegrity`'s source scan widens to the whole shell.** It reads exactly three files
   today — `Sidebar.tsx`, `LibraryPage.tsx`, `ToolsPage.tsx` — which is why two dead affordances
   survive in files it does not read: `StatusMenu.tsx:364` navigates to `/library/proposed-changes`,
   which is unmounted and silently redirects home, and `MobileMoreSheet.tsx:48-51` sets
   `uiStore.showSettings`, which has no consumer anywhere. The scan globs every file under the new
   `app/`, `screens/` and `panels/` trees.

5. **Both dead affordances are fixed rather than carried across.** The proposed-changes link becomes
   a non-interactive count — the Mac owns that surface under `ADR-0013` — and the mobile sheet is
   deleted along with `showSettings` and `setShowSettings` in `stores/uiStore.ts`. `ADR-0057` point 5
   applies: the affordance leaves with the capability it cannot reach.

6. **Nothing in the shell constructs an audio engine.** This is the property `ADR-0017` gives the
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
navigation needs.

**Different chrome per viewport, as today** — sidebar on desktop, bottom nav plus sheet on mobile.
Rejected as the source of two of the defects in point 4: the mobile-only components are the ones the
navigation test does not read and nobody opens, which is exactly where a dead affordance survives.

## Consequences

- **Positive** — the administration tool stops constructing an audio engine, a scrobbler and a
  play-tracker on every page load.
- **Positive** — one navigation implementation replaces three (`Sidebar`, `MobileBottomNav`,
  `MobileMoreSheet`), and the one that remains is the one covered by tests.
- **Positive** — two live dead-affordance defects are fixed, and the check that would have caught
  them is widened so the next one fails a build.
- **Tradeoff** — horizontal space is finite. Three destinations fit comfortably; a fourth or fifth
  would push toward an overflow control, which is the failure mode a rail does not have.
- **Tradeoff** — `Sidebar.tsx` is deleted despite being recently built and fit for its purpose. That
  is a real cost and it is being paid for the shape of the product rather than for a defect in the
  component.
- **Follow-up** — `components/TrackEdit/` (2,115 lines) is mounted by the shell today. Whether the
  administration tool still edits track metadata is a genuine question this ADR does not answer; it
  is kept mounted only if a screen opens it.
