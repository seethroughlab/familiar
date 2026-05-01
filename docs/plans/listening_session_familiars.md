# Listening Session Familiars

## Summary
Add a subtle `familiar` system to Listening Sessions using abstract presence objects rather than face avatars. The v1 visual direction is a `light familiar`: a small floating token or mote with restrained glow, shape, and motion, shown in a shared mini-room above the roster/chat on both the Familiar session panel and the public guest page.

Each participant gets a tiny customization palette:
- `shape family`
- `base color`
- `accent motion`

Expression is limited to short-lived micro-reactions:
- `cheer`
- `pulse`
- `wave`
- `spark`

Guests configure their familiar during join and it persists browser-locally on the `familiar-sessions` site. Familiar users get defaults from their current profile color and can override them locally per profile in the app without introducing account/backend persistence in v1.

## Key Changes
### Session model and wire protocol
- Extend session participant payloads to include an optional `familiar` object with a minimal schema: `variant`, `color`, `accent`, `seed`.
- Accept `familiar` on `create`, `join`, and `join_guest` messages.
- Store familiar state in relay memory alongside participant state.
- Include familiar data in:
  - `session_created`
  - `session_joined`
  - `user_joined`
  - full participant snapshots
- Add a `update_familiar` message so the in-session editor can sync changes live.
- Add a new WebSocket message for reactions, `reaction { kind }`, rebroadcast as `user_reaction { user_id, kind, timestamp }`.
- Keep reactions ephemeral only; they do not become chat messages or durable history.

### Guest experience (`familiar-sessions`)
- Add a lightweight pre-join familiar picker to the guest flow in `GuestListener.tsx`.
- Render a compact shared mini-room once connected, showing all familiars together with live/listening state and transient reactions.
- Persist guest familiar choices in localStorage keyed to the guest site.
- Keep the existing guest chat and playback surfaces intact around the new room.

### Familiar app experience (`familiar`)
- Extend the Listening Session hook to send and receive familiar metadata, live familiar edits, and reaction events.
- Update the session UI to add:
  - a mini-room strip above the participant list
  - a compact reaction bar
  - a tiny familiar editor for the current user
- Default familiar color from the selected Familiar profile’s `color`; ignore uploaded profile photos in v1.
- Persist Familiar-side familiar overrides locally, keyed by selected profile ID, so no backend migration is required.

### Visual and interaction rules
- Avoid faces, limbs, mascots, or emoji-heavy UI.
- Use muted materials and motion: soft glow, ring expansion, slight drift, subtle brightness shifts.
- Show presence through state, not illustration:
  - listening: steady idle
  - reacting: brief flare or ripple
  - disconnected or weak: dimmed presence
- Keep the room compact and informational, not a full scene or game board.

## Test Plan
- Relay WebSocket tests:
  - create/join/join_guest with familiar metadata
  - participant snapshots include familiars
  - reaction broadcast reaches all participants
  - live familiar edits broadcast via `user_updated`
- Frontend hook and UI checks:
  - familiar defaults derived correctly
  - local familiar overrides persist and reload
  - reactions appear and expire cleanly
  - clients without familiar data fall back to generated defaults
- UI acceptance:
  - mini-room works on the Familiar session panel and public guest layout
  - reactions never block audio/chat controls
  - design stays minimal and non-cartoony in both light and dark themes

## Assumptions and Defaults
- v1 uses `presence objects`, specifically `light familiars`, not profile photos and not character avatars.
- v1 is `mini-room` first, not just roster decoration.
- v1 customization is a `tiny palette`, not a builder.
- v1 expression uses `micro-reactions`, not rich emote systems.
- Guest persistence is browser-local only.
- Familiar-profile persistence for familiars is local to the client for now; no new backend profile fields or migration in v1.
- Existing chat, kick, playback sync, and WebRTC behavior remain unchanged aside from carrying familiar and reaction state.
