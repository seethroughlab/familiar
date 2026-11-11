# ADR-0177: Playlist Writes From MCP Notify Attached Clients

Status: accepted

Date: 2026-11-10

Implementation:

- **2026-11-10: built on both ends.** Server: `PlaybackCommandChannel.notify` in
  `backend/app/services/playback_commands.py` puts the notice on every attached player's queue
  (sharing `send`'s drop-oldest `_enqueue`), and `backend/app/mcp/server.py` calls it after a
  `PLAYLIST_WRITING_TOOLS` call whose result has no `error` (#476, in v0.2.0-beta24). Tests:
  `TestNotify` in `tests/test_command_channel.py`, `TestPlaylistWritesNotifyClients` in
  `tests/test_mcp_server.py`. Client: `familiar-apple` #269 decodes `playlists_changed`, reloads
  `PlaylistsStore` (coalescing a notice that arrives mid-load) and reloads an open playlist's
  detail; in app 1.7 (build 80, released on the App Store on iOS and macOS 2026-11-11).

Extends [ADR-0044](ADR-0044-mcp-clients-actuate-playback-through-a-command-channel.md)

## Context

A playlist made through MCP did not appear in the running Mac app. On 2026-11-10 a host created
"Recently Added — Last 4 Sessions" (791 tracks) with `create_playlist_from_items` and
`add_tracks_to_playlist`; `list_playlists` returned it first, and the Mac's sidebar and All Playlists
screen did not show it. The server log showed no `GET /api/v1/playlists` from the Mac in the
following half hour.

The client is behaving as written. In `familiar-apple`, `PlaylistsStore.load()` runs only while the
store is empty (`LibraryView.loadSectionIfNeeded`, `guard !playlistsStore.hasLoadedAnything`), and
`LibraryCacheCoordinator.refreshPlaylists()` runs on launch. Nothing tells a running app that a
playlist was written somewhere else, so the listener asks for a playlist in a conversation and then
has to quit the app to see it.

ADR-0044's channel is the only server-to-client path, and it was built for imperatives addressed to
one player: `send` picks the most recently attached client that declared the needed capability.

## Decision

1. **A new message on the existing channel: `{"type": "playlists_changed"}`.** It means "re-fetch
   your playlists"; it carries no playlist data (ids travel, not state, as ADR-0044 already holds).
2. **It is a notice, delivered to every attached client of the profile**, through a new
   `PlaybackCommandChannel.notify`. Unlike `send` it has no target, requires no capability, and does
   not raise when nobody is attached: the next launch fetches fresh, so there is nothing to report.
3. **No capability is declared for it.** Older clients already ignore unknown types
   (`PlaybackCommand.decode` returns nil). A new capability name would make a newer client's
   subscription fail with a 400 against an older server, which rejects unknown names.
4. **The MCP dispatcher sends it after a playlist-writing tool succeeds**: `create_playlist_from_items`,
   `add_tracks_to_playlist`, `generate_playlist`, `select_diverse_tracks`
   (`PLAYLIST_WRITING_TOOLS` in `backend/app/mcp/server.py`). A result carrying `error` sends nothing.
5. **The Apple clients reload their playlist list on receipt**, and reload an open playlist's detail.

## Alternatives Considered

- **Poll the playlist list on a timer or on window focus.** Rejected: ADR-0011 refuses timer-driven
  refresh as background cost, and focus does not change while a listener talks to an assistant in
  another window beside the app, which is exactly the case that failed.
- **Send it with `send` to one player.** Rejected: the Mac and the phone are both showing the list,
  and a notice that reaches only the most recently attached one leaves the other stale.
- **Notify from `app/operations/` or the REST routes, covering every writer.** Deferred, not
  rejected: playlist writes are spread across `operations/playlists.py`, the REST `crud`/`generate`
  routes, the LLM handlers and smart-playlist materialisation. The MCP dispatcher is the one place
  that covers the reported case without touching all of them; REST writes come from a client that
  already refreshes itself.
- **Carry the changed playlist in the message.** Rejected: a hand-parsed copy of `PlaylistResponse`
  outside the generated client, the drift ADR-0044 avoided by sending ids.

## Consequences

- **Positive**: a playlist made or extended in a conversation appears in every open app within a
  second, with no relaunch.
- **Positive**: additive on both ends. Old clients ignore the message, and new clients against an
  old server simply never receive it.
- **Tradeoff**: the channel now carries one non-imperative, broadcast message alongside ADR-0044's
  targeted commands. `notify` is a separate method so the two cannot be confused.
- **Tradeoff**: a client that is not attached at that moment (app closed, reconnecting) misses the
  notice, as with any command. Its launch refresh covers that case.
- **Follow-up**: a playlist written by one Apple client through REST still does not reach another
  running client. If that matters, move the notice into the shared operations layer.
