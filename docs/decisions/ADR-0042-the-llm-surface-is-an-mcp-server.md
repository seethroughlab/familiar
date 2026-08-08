# ADR-0042: The LLM Surface Is an MCP Server, Not a Chat Client

Status: proposed

Date: 2026-08-07

Supersedes [ADR-0022](ADR-0022-chat-is-built-native-and-hidden-without-a-provider.md).

## Context

Familiar owns an entire LLM client stack. The backend module is 2,092 lines
(`backend/app/services/llm/`, excluding the handler package), the chat route is 210
(`backend/app/api/routes/chat.py`), the web client is 1,479
(`components/Chat/` 965, `api/chat.ts` 197, `services/chatService.ts` 269,
`hooks/useChatAvailability.ts` 48), and `familiar-apple` carries a native chat of roughly the same
size again, shipped under ADR-0022 in `familiar-apple` #54 and #55.

**The premise ADR-0022 was written against has not improved.** That ADR recorded the
deprioritisation honestly in its own Context — *"AI chat is becoming less of a priority through
usage. I just didn't end up using it as much as I thought. I still like the idea of the CLAP and
other analysis for creating playlists, but the actual chat is a lower priority for now"* — and then
built chat anyway, for a reason that was correct at the time: surfaces existed that *led* to chat
and could not complete the journey, so the choice was between building the destination and
permanently removing the paths to it. **This ADR takes a third option that did not exist when
ADR-0022 was written: move the destination out of Familiar entirely.**

**The asset is the tools, and the tools are not chat-specific.** `services/llm/handlers/` is 2,468
lines implementing 30 tools against this library's own analysis — `semantic_search` over CLAP
embeddings, `filter_tracks` with 46 properties spanning audio features and deep analysis,
`get_feature_distribution` (which exists so a model can calibrate thresholds to *this* collection
rather than to a general idea of "high energy"), `get_track_analysis`. What sits on top of them —
a provider abstraction, a tool loop, an SSE encoding, and two hand-written clients — is generic
plumbing that every MCP host already provides.

**Verified against the repo at write time:**

- **30 tools in `MUSIC_TOOLS`** (`services/llm/tools.py`, 888 lines). The executor's dispatch map
  has 31 entries because `filter_tracks_by_features` is a back-compat alias for `_filter_tracks`.
- **Exactly three of the 30 require a Familiar client to act.** `get_visible_tracks` answers only
  because the client uploaded `visible_track_ids` with the request; `queue_tracks` and
  `control_playback` write to in-memory fields on `ToolExecutor` and touch no server state at all
  (`handlers/playback.py:48` and `:72`). The other **27 are pure data or durable server-side
  writes**, and port unchanged.
- **The actuation is entirely client-side.** `service.py` drains those in-memory fields into
  trailing `queue` and `playback` SSE events, which only become real inside the event switch in
  `packages/frontend/src/components/Chat/ChatPanel.tsx` — `setQueue(tracks, 0, {type:'ephemeral'})`
  on `usePlayerStore` at the `queue` case, and `setIsPlaying`/`playNext`/`playPrevious` at the
  `playback` case. **The server cannot play a note and never could.**
- **The server holds no conversation.** There is no `Conversation`, `ChatSession` or `ChatMessage`
  model anywhere in `app/db/models/`; `ChatRequest.history` carries up to 100 messages on every
  request and history lives in the browser's IndexedDB via `services/chatService.ts`. Retiring the
  web client destroys no server-side record, because there is none.
- **`POST /chat` has no callers.** Every client uses `/chat/stream` and `/chat/status`. The
  non-streaming endpoint — the one whose `ChatResponse` carries `queued_tracks` and
  `playback_action` — has never been used by anything in either repository.

**A premise that was checked and turned out false, recorded so nobody re-derives it.** The
attractive version of this decision is "retire the chat and delete the LLM integration". That is
wrong: `backend/app/api/routes/library_discover.py:197` calls
`get_provider().complete_utility(...)` to generate the curated "Listening Ideas" prompts. **The
provider layer and a server-side API key survive this ADR**, and the deletion is smaller than it
first appears.

**`ToolExecutor` carries two pieces of chat-shaped context, and only one of them ports.**
`profile_id` is load-bearing in nine paths across the exposed tools — favourites and play-history
filters in `handlers/search.py:284-499`, unheard/deep-cut discovery and the Spotify import lookup in
`handlers/discovery.py:203-496`, and playlist ownership in `handlers/playlists.py:154-169`. It
arrives today from the `X-Profile-ID` header on the chat request, and MCP has no equivalent.
`user_message` is the harder one: it is the listener's raw turn, used for
`Playlist.generation_prompt` (`handlers/playlists.py:173`) and for `_playlist_name_from_request()`
(`executor.py:146`), which strips filler like "can you play me some…" to name a playlist. **An MCP
host does not pass the user's turn to a tool call**, so this is not a value that can be plumbed
through — it has to become an argument or be dropped. Point 9 decides both.

**Point 3's risk was measured rather than assumed, and it runs in both directions.**
`SYSTEM_PROMPT` is 11,010 characters, but most of it is chat-loop control — "SEARCH ONCE, THEN
QUEUE", "STOP CONDITIONS", "you've made 2 searches → STOP" — which exists to stop a chat agent
looping and is **irrelevant under MCP**, where the host runs its own loop and the listener can
iterate. The portable subset is much smaller. What makes it load-bearing is *what is in it*.
Measured against the live library (25,697 analysed tracks) through `get_feature_distribution`:

| feature | min | median | mean | max |
|---|---|---|---|---|
| `energy` | 0.0 | **0.826** | 0.809 | 1.0 |
| `valence` | 0.0 | **0.848** | 0.825 | 1.0 |
| `danceability` | 0.0 | **0.149** | 0.150 | 0.989 |
| `acousticness` | 0.159 | 0.491 | 0.486 | 0.866 |
| `instrumentalness` | 0.0 | **1.0** | 0.999 | 1.0 |

A model applying conventional thresholds gets `energy_min=0.8` → **half the library**,
`valence_min=0.7` → **nearly all of it**, `danceability_min=0.5` → **almost nothing**. Because the
error runs in both directions it cannot be corrected by a constant, nor by a model noticing that
results look consistently wrong. This is exactly the knowledge `get_feature_distribution`'s
description already tells a model to fetch, and exactly what is lost if descriptions stop carrying
it.

**A second trap lives only in `SYSTEM_PROMPT` and in no tool description.** `search_library`
applies a diversity filter capping results at **2 per artist**, so "play me some [artist]" through
it silently returns two tracks. The prompt says "do NOT use search_library here"; the tool's own
description says nothing.

**Four defects found while surveying, none of which should be carried across:**

- **`clear_existing` is inert at both ends.** `_queue_tracks` accepts it and echoes it in its
  response but never assigns `self._clear_queue` (`handlers/playback.py:22-68`), so
  `get_queued_tracks()` always returns the constructor default. `ChatPanel` then ignores the flag
  too and always replaces the queue. The model has never been able to request an additive queue.
- **`ChatResponse.playback_action` is typed `dict[str, Any] | None`** while
  `ToolExecutor._playback_action` is a plain string (`"play"`, `"pause"`, `"next"`, `"previous"`).
- **`ChatResponse` silently drops two of the nine event types.** `ephemeral_playlist_created` and
  `navigate` have no representation in it — the same undocumented pair ADR-0022's implementation
  notes recorded.
- **`handlers/playlists.py` `_save_as_playlist` is unreachable.** No dispatch entry, no
  `MUSIC_TOOLS` definition.

**On reach.** Familiar has no inbound authentication of any kind: the whole auth surface is an
`X-Profile-ID` header (`app/api/deps.py`), profile IDs are enumerable through an unauthenticated
`GET /api/v1/profiles`, **158 of the 261 operations in the committed `openapi.json` carry no
security requirement at all**, and CORS admits any single-label host or bare IPv4 on any port with
`allow_credentials=True` and `allow_headers=["*"]` (`app/main.py:365-374`). The security model is
stated plainly in `packages/frontend/src/services/profileService.ts:5`: *"No passwords needed -
protected by Tailscale."* That is sufficient for Claude Desktop and Claude Code, which run on the
listener's own machine. It is not sufficient for a hosted third-party client, and this ADR does not
pretend otherwise — point 7 draws that line rather than blurring it.

There is precedent for the shape of that mistake. `d36c906` added a Subsonic API "for CarPlay and
native music app support" with its own bcrypt-hashed credentials table; `bc53ef0` shelved it to
`feature/subsonic-api` and `migrations/versions/20260306_drop_subsonic_creds.py` dropped the table.
The `bcrypt` dependency in `backend/pyproject.toml` is the only thing left of it.

## Decision

1. **Familiar exposes an MCP server, and it is the LLM surface.** It is hosted **in-process in
   FastAPI**, as streamable HTTP mounted at `/mcp`. The tools need the request's `AsyncSession`, the
   app settings service and the `handlers/` package; a separate process would re-implement 27 tools
   against the REST API and drift from them. This is the same reasoning
   [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) applies to the generated client — one
   contract, generated from the thing itself, not maintained alongside it.

2. **The exposed surface is the 27 tools that do not require a Familiar client, minus
   `fetch_webpage`.** The three that require one — `get_visible_tracks`, `queue_tracks`,
   `control_playback` — are out of scope here and are the subject of
   [ADR-0043](ADR-0043-mcp-clients-actuate-playback-through-a-command-channel.md).
   `fetch_webpage` is dropped outright: it is a server-side URL fetcher on an API with no inbound
   authentication, and the host's own web access does the job better. **That leaves 26 tools.**

3. **Tool descriptions carry the sequencing knowledge the system prompt used to, and the claim is
   tested before the port rather than after.** `service.py` builds a system prompt encoding real
   operating knowledge — call `identify_track` before `find_similar_tracks`; call
   `get_feature_distribution` before choosing a threshold; do not reach for `search_library` when
   you want more than two tracks by one artist. **MCP guarantees no system prompt**, so the
   descriptions and the server's `instructions` are the only channel that reaches every host.
   **Only the portable subset moves.** The loop control does not: it exists to stop a chat agent
   looping and would actively mislead a host that runs its own loop.
   `backend/scripts/spike_mcp_server.py` exists to settle this — two arms over five real tools,
   logging every call, so "descriptions are enough" is a measurement rather than a hope. This is
   the point most likely to be skipped and the one most likely to make the result feel worse than
   the chat it replaced.

4. **Familiar keeps the external tools that join to the library, and cedes open-ended search to the
   host.** `get_similar_artists_in_library` (Last.fm ∩ this library), `get_spotify_unmatched` and
   `recommend_bandcamp_purchases` compute something no host can: the intersection of the outside
   world with what is already here. Familiar keeps those. It stops trying to be a worse search
   engine than the one already sitting in the client.

5. **The chat clients are retired — `chat.py`, the web chat, and the Swift chat — and the provider
   layer is not.** `library_discover.py:197` is a second consumer of `complete_utility`, so
   `providers.py`, `providers_anthropic.py` and `providers_openai.py` survive along with the
   server-side key. Only the tool loop in `service.py`, `models.py` and the chat route go.

6. **"Listening Ideas" gets its destination decided here, not left to break a fourth time.** The
   prompts at `GET /library/discover/prompts` were written to be pressed and to open a chat. With no
   chat anywhere, they are affordances whose destination is not mounted — the exact defect shape of
   `familiar` #70, #74 and #76. **The endpoint and the cards are removed with the chat clients.**
   Reinstating them as copyable prompts for an external host is a product decision, not a
   consequence of this one, and it does not get smuggled in here.

7. **Reachability is Tailscale and localhost. Public exposure is gated behind
   [ADR-0044](ADR-0044-familiar-authenticates-inbound-requests.md).** Claude Desktop and Claude Code
   reach the server on the machine or the tailnet the listener already runs. Hosted third-party
   clients cannot, and making them able to means auditing 158 unauthenticated operations and
   inventing an inbound credential. That is a larger decision than this one and it is not a
   prerequisite for the value here. **The MCP mount does not bind or advertise publicly by default**,
   so nobody publishes their library by following a quickstart.

8. **The four defects in the Context are fixed or dropped, not ported.** `clear_existing` becomes
   real or is removed from the schema; `_save_as_playlist` is deleted; the `ChatResponse` type
   mismatch and its two dropped event types disappear with the route.

9. **The MCP session is bound to one profile, and `generation_prompt` becomes an explicit
   argument.** The profile is configured per connection, not passed per call: nine paths depend on
   it, a tool that took it as a parameter would let a model guess at another listener's favourites,
   and a wrong value is silent rather than an error. **A connection with no profile bound fails at
   connect time, naming the reason** — the ADR-0022 point 3 rule that a surface which cannot work
   must not present itself as working. Separately, `create_playlist_from_items` gains an explicit
   argument for the intent behind the playlist, because the host never passes the listener's raw
   turn and `Playlist.generation_prompt` would otherwise be empty on every MCP-created playlist.
   `_playlist_name_from_request()` goes with the tools that used it.

## Alternatives Considered

**Keep the built-in chat and add MCP alongside it.** The no-deletion option, and the safe one: the
chat keeps working for anyone with no MCP-capable client, and MCP becomes an extra. Rejected because
it makes the maintenance situation strictly worse — three LLM surfaces instead of two, all sharing
the tool layer, each needing the fix when a tool schema changes. ADR-0022 already recorded "a second
chat implementation to keep working" as a tradeoff at six commits in six months; this would be a
third. The deprioritisation that ADR-0022 recorded is the argument: a surface nobody uses does not
earn a permanent seat.

**Run the MCP server as a separate local process on the Mac, talking to the REST API.** Genuinely
attractive on security grounds — stdio transport, no network listener, no auth question at all, and
it would work for Claude Desktop today with nothing else built. Rejected because the tools do not
live in the REST API. 26 of them would have to be re-implemented against endpoints that do not
expose the same shapes: there is no REST endpoint for `semantic_search`, `get_feature_distribution`
or `filter_tracks`' 46 properties. It would be a second implementation of the most valuable code in
the project, guaranteed to drift, in exchange for a deployment property.

**Expose the existing `openapi.json` as MCP tools automatically.** 261 operations, already typed,
already lint-gated, zero new tool definitions. Rejected because the REST surface is the wrong
granularity and the wrong shape: it includes `DELETE /library/missing/batch` and 13 S3-backup
operations, and it lacks the analysis-aware tools entirely. ADR-0007 point 2 already established
that the generated surface is a deliberate subset rather than the whole API; the same judgement
applies here, and the subset an LLM wants is not the subset a client wants.

**Keep chat and make it an MCP *client* instead**, so Familiar's own chat and external hosts share
one tool definition. Preserves the in-app surface and still gets the tools out. Rejected because it
keeps every line this ADR is trying to delete — the provider abstraction, the tool loop, the SSE
encoding, two hand-written clients — and adds an MCP layer underneath them. It is the most code of
any option on the table, to preserve a surface that measured use says is not wanted.

**Do nothing.** Chat works, it is built, both platforms have it, and its cost is already sunk.
Rejected on the strength of point 4's asymmetry: the analysis tools are the part with value and
they are locked inside a client nobody opens, while the client that *is* open all day cannot reach
them.

## Consequences

- **Positive.** The 2,468 lines in `handlers/` — the part of this project with the most
  library-specific value — become reachable from the tools the listener already uses all day,
  instead of from a surface that measured use says is not opened.
- **Positive.** Roughly 3,300 lines retire across two repositories, and with them the tradeoffs
  ADR-0022 accepted: the hand-rolled untyped SSE reader, the `URLSession.AsyncBytes.lines`
  empty-line trap, the nine-versus-seven undocumented event types, the two error shapes, and the
  per-device conversation history that never synced.
- **Positive.** Model choice and token cost move to the listener's own subscription. The hardcoded
  `claude-sonnet-4-5-20250929` pin in `services/llm/models.py` stops being Familiar's problem for
  the chat path.
- **Positive.** Familiar stops maintaining a worse version of capabilities the host already has —
  web search, conversation history, retry, model selection, prompt caching.
- **Tradeoff.** Familiar no longer has a working LLM surface of its own. A listener with no
  MCP-capable client loses the capability entirely, where today one server-side key served every
  client. This is the real cost of the decision and it is not mitigated.
- **Tradeoff.** Point 3 is a genuine quality risk. The system prompt is a reliable channel and tool
  descriptions are a weaker one; a host that ignores them will threshold `energy` without calibrating
  and produce worse playlists than the chat did. This must be measured, not assumed.
- **Tradeoff.** Ephemeral, explicitly-unsaved playlists have no equivalent. An MCP tool creates a
  real `Playlist` row or nothing. Arguably better, but it is a behaviour change and the staging step
  disappears.
- **Tradeoff.** Point 9 binds a connection to one profile, so a household with several configures
  several connections and a host cannot switch between them mid-conversation. That is the cost of
  refusing to let a model guess at whose favourites it is reading.
- **Tradeoff.** `get_visible_tracks` dies with the chat panel. "These tracks", "this list", "what
  I'm looking at" become unanswerable, and no MCP host can supply a viewport Familiar owns.
- **Tradeoff.** Point 6 removes a feature that was restored only days ago, and removes an endpoint
  that ADR-0022's implementation notes call out as the reason no third bridge message was needed.
- **Follow-up.** [ADR-0043](ADR-0043-mcp-clients-actuate-playback-through-a-command-channel.md) —
  playback actuation. Until it lands, MCP produces artifacts and answers; it does not play anything.
- **Follow-up.** [ADR-0044](ADR-0044-familiar-authenticates-inbound-requests.md) — inbound
  authentication, and the prerequisite for point 7's public half. It is worth noting that the 158
  unauthenticated operations are a finding about Familiar today, not a new risk created here.
- **Follow-up.** `ADR-0022` flips to `superseded by ADR-0042` when this is accepted, not before.
- **Follow-up, unrelated to MCP and found by measuring for point 3.** `instrumentalness` has median
  **1.0** and mean **0.999** across 25,697 analysed tracks — it is saturated and cannot discriminate
  anything, yet `filter_tracks` exposes `instrumentalness_min` as a usable filter. Either the
  extractor is wrong or the filter should go. `danceability` at median 0.149 is worth a second look
  for the same reason.
- **Follow-up.** The `bcrypt` dependency is vestigial from the shelved Subsonic API and should be
  removed, or deliberately kept for ADR-0044 to build on.
