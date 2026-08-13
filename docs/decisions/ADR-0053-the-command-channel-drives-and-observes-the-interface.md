# ADR-0053: The Command Channel Drives and Observes the Interface

Status: proposed

Date: 2026-08-12

Extends [ADR-0044](ADR-0044-mcp-clients-actuate-playback-through-a-command-channel.md)

## Context

[ADR-0044](ADR-0044-mcp-clients-actuate-playback-through-a-command-channel.md) built a per-profile
SSE channel from server to client and proved it end to end — Claude Desktop to sound. Its point 11
divided everything an MCP host might want into three categories: server-side state, transient device
actions, and device-local preferences. Two of those three travel on the channel.

**Navigating the interface is a fourth category, and the vocabulary for it already exists.**
`SidebarItem` in `FamiliarKit` enumerates every destination the Mac and phone can be rooted on —
`home`, `section(.tracks/.albums/.artists/.playlists)`, `smartPlaylists`, `musicMap`, `discover`,
`pendingReview`, `proposedChanges`, `mixtapes`, `favorites`, `downloads`, `settings`. A "show me the
albums" imperative is the same shape as "play", against a list that is already closed and named.

The prompt is narrower than the capability. The website (ADR-0039 point 4 and its screenshot
follow-up) has no images of the native clients at all — `screenshots/` is entirely the web app,
captured by a Playwright spec that by construction cannot photograph a Mac app. Meanwhile every
attempt to drive that app from tooling has failed: synthetic media keys do nothing, accessibility
traversal finds nothing, and the standing rule in this project is not to guess at click coordinates
on a real desktop. **The app can do both of these things trivially from the inside**, and there is
already a channel pointed at its inside.

### The thing this changes

ADR-0044 point 2 chose SSE over a WebSocket with a stated reason: *"Commands are one-way, so the
return half of a socket would be unused."* A screenshot is a return. That premise is not wrong, but
it no longer covers everything the channel is asked to carry, and reversing it silently would be
worse than recording it.

### What a capture must not become

macOS offers screen capture through `ScreenCaptureKit`, which photographs displays and other
applications and demands the Screen Recording permission to do it. That is the wrong instrument
twice over: it prompts, and once granted it can see everything on the machine. An application can
render *its own* windows with no permission at all, and that is the only thing this needs.

## Decision

1. **The channel gains a fourth category: interface navigation.** An imperative naming a
   `SidebarItem`, applied by the client to its own root selection. Server-side state is still
   written directly and still needs no channel; this joins transient actions and preferences.

2. **The destination vocabulary is `SidebarItem`, not free text.** The tool advertises exactly the
   cases that exist, so an unknown destination is refused by the schema rather than accepted and
   dropped. A "navigate" that lands nowhere is the affordance-with-no-destination defect this
   project has hit five times.

3. **Artifacts return over HTTP, not over the channel.** The client `POST`s a capture to
   `/playback/artifacts/{request_id}`; the SSE stream stays one-way and ADR-0044 point 2's
   reasoning survives intact — the return half of a *socket* would still be unused, because the
   return is a request the client makes when it has something to send.

4. **A request id correlates the two halves**, minted by the server when it issues the command and
   carried back on the upload. It is not a device identity and does not reopen
   [ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md) point 5: it names one
   outstanding question, lives in memory, and dies when the question is answered or times out.

5. **The tool waits, with a deadline, and answers either way.** A capture that never arrives returns
   "the client did not answer in time" rather than hanging — ADR-0044 point 5's rule, which is
   ADR-0017 point 4's rule one layer further out. Nothing on this channel may spin.

6. **A capture is the application drawing its own window, never a screen recording.** No permission
   prompt, and by construction it cannot photograph anything but Familiar — which matters because
   the machine this runs on is somebody's desktop, with their mail on it.

   **Through the window's `CALayer`, not through `cacheDisplay`.** This was written the other way
   round and corrected by running it: `cacheDisplay(in:to:)` drives `draw(_:)` down the view tree,
   and SwiftUI's macOS views are layer-backed and mostly do not implement it — so the capture came
   back with the sidebar entirely black while the track table, an `NSTableView` underneath, drew
   fine. Deterministically; two consecutive captures were byte-identical, so it was not a race.
   `CALayer.render(in:)` walks the tree that actually holds the pixels, and needs its context
   flipped first or the whole window arrives upside down.

7. **Both are capability-gated**, per ADR-0044 point 12. `navigate` and `screenshot` join the
   declaration a client makes when it subscribes, so the tool surface offers them only when the
   attached client can actually do them. The phone declares navigation and not capture; the web app
   declares neither.

8. **Artifacts are held in memory and dropped once read.** No table, no directory, no retention
   rule to get wrong. A screenshot of somebody's library is not something to accumulate on a server
   because it was easier than deleting it.

## Alternatives Considered

- **Have the MCP host drive the Mac through accessibility APIs.** The obvious answer, needs no
  Familiar code, and works for any application. Rejected on evidence: this project has already tried
  it. Synthetic media keys and AX traversal both failed against this app, and the fallback —
  guessing at screen coordinates on a real desktop — is how a stray click deletes something. The app
  knows where its own destinations are; asking it is both easier and safer.

- **Screen capture via `ScreenCaptureKit`.** Higher fidelity, captures what a person would actually
  see including window chrome. Rejected: it requires the Screen Recording permission, which is a
  prompt and a standing grant to photograph the whole machine, in exchange for pixels this app can
  produce about itself for free.

- **A WebSocket, replacing SSE.** The honest reading of "we now need a return path" is that the
  transport should carry it. Rejected because the return is rare, large and binary — a screenshot is
  hundreds of kilobytes — and multiplexing that into the command stream would make the common case
  (a four-byte transport imperative) pay for the rare one. An upload is a better fit for an upload.

- **Write captures to disk and return a path.** Simpler to implement and easy to debug. Rejected by
  point 8: it turns a transient answer into an accumulating pile of images of somebody's library,
  with a retention policy nobody will write.

- **Do nothing, and screenshot the app by hand.** Genuinely reasonable for the website alone — it is
  ten minutes of somebody's time. Rejected because the capability is worth more than the errand: an
  MCP host that can see the interface can also check its own work, and this project has shipped
  three defects this month whose common shape was a screen that renders and does nothing.

## Consequences

- **Positive:** the native clients can finally be photographed for the website, which ADR-0039's
  follow-up has been blocked on since it was written.
- **Positive:** an MCP host can *look* at the app, not only act on it — the first return path this
  channel has had.
- **Positive:** navigation reuses a closed enum that already exists, so the tool cannot name a
  destination the app does not have.
- **Tradeoff:** the channel is no longer purely one-way at the system level, even though the SSE
  stream still is. ADR-0044 point 2's sentence needs reading alongside this ADR rather than alone.
- **Tradeoff:** a capture is the app's own drawing, so it will not show window chrome, the menu bar,
  or anything overlapping it — the title-bar strip comes back empty. For screenshots of the
  interface that is arguably better; for reproducing a visual bug involving a system control it is
  worse.
- **Tradeoff:** rendering a layer tree is not the same as what the compositor puts on screen.
  Anything the window server draws on top — a sheet from another process, a tooltip, the
  title bar — is absent by construction, and a capture is therefore evidence about the app's own
  view tree rather than about what a person saw.

  **Measured, and worse than "no chrome" suggests.** Against the same window in one session, the
  sidebar rendered on some destinations and came back black on others, and the smart-playlists
  screen came back blank and byte-identical across two attempts twelve seconds apart —
  deterministic rather than flaky, and unexplained. A layer walk sees what the app *asked* to be
  drawn, not what was drawn.

- **The two jobs separate, and only one of them is this ADR's.** For website screenshots,
  `screencapture -o -x -l <windowid>` — the system tool, aimed at one window — produced every
  destination correctly on the first attempt, chrome included, with no black sidebars and no blank
  screens, because it reads what the compositor produced. It needs the Screen Recording permission,
  which is exactly what point 6 refuses to make the *application* ask for. A person capturing on
  their own machine is not the application and can grant it to a terminal for a minute.

  So: the in-app capture stays the MCP tool — permission-free, and good enough for an assistant
  checking its own work. Marketing screenshots use the system tool, with navigation still driven
  over this channel so nothing has to be clicked.
- **Tradeoff:** two more capabilities to keep honest. A build that declares `screenshot` and cannot
  produce one is exactly the failure point 7 exists to prevent, and nothing but care enforces it.
- **Follow-up:** the phone could declare `screenshot` too — `UIGraphicsImageRenderer` over the key
  window is the same idea — but iOS captures are not what the website needs first.
- **Follow-up:** navigation is root-level only. Opening a *specific* album or playlist means naming
  one, which is a larger vocabulary and a second decision.
