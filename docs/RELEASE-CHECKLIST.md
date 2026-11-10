# Release Checklist

Checks a person makes before tagging a server release, because automation cannot make them.
Everything a machine can check runs in CI; this file is for what it cannot.

## Accessibility smoke test (ADR-0174 point 8)

`packages/web/e2e/accessibility.spec.ts` runs axe-core on Overview, Library, Analysis and Server, at
desktop and phone widths and in an error state, and fails CI on a violation. That catches missing
names, headings, landmarks and contrast. It cannot tell whether the pages can actually be *used*
without a mouse or a screen. Before a release, on the web admin against a real server:

**Keyboard only** (no mouse or trackpad):

- [ ] `Tab` from the top reaches the destinations, then the section rail, then the page, in that
      order, and every focused control shows a visible focus ring.
- [ ] Every action on Overview, Library → Sync, Analysis → Status and Server → Access can be
      triggered with `Enter` or `Space`.
- [ ] Analysis → Status: a failure group's **Details** opens with `Enter`, and **Copy details** is
      reachable after it.
- [ ] Any dialog you open takes focus, keeps it inside, closes with `Escape`, and returns focus to
      the control that opened it.

**Screen reader** (VoiceOver: `⌘F5` on macOS):

- [ ] The rotor's headings list reads Familiar, then the destination, then its sections.
- [ ] Destinations and sections are announced as links, with the current one identified.
- [ ] Analysis → Status: the phase table is announced as a table with its column headers, and a
      failure group reads its summary before its details.
- [ ] Nothing announces only as "button" or "image" with no name.

Note anything that fails in the release's pull request, and either fix it or open an issue before
tagging.
