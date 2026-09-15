# ADR-0116: Familiar Acquires Through a Soulseek Client It Does Not Own

Status: accepted

Date: 2026-09-13

Extends [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md), which made the LLM surface an MCP
server, and applies [ADR-0022](ADR-0022-chat-is-built-native-and-hidden-without-a-provider.md)
point 3 — a destination that cannot answer is absent, not present and failing — to a tool set for
the first time.

Implementation:
- **Accepted 2026-09-15.** Built and merged with ADR-0117 in #306 (2026-09-14) ahead of acceptance, on the operator's own slskd.

## Context

Familiar's discovery tools stop at the edge of the library. `get_discovery_recommendations` names
artists the listener does not have; `get_similar_artists_in_library` reports which similar artists
are absent; `recommend_bandcamp_purchases` and `search_bandcamp` point at somewhere to buy. Every
one of them ends the same way: the host says "you don't have this", and the listener goes and gets
it by hand, somewhere else, and then runs a sync.

On 2026-09-13 a host was asked for new artists from recent listening and produced fourteen
candidates, checking each against the library first. Eleven were already there — the library is
deep — and the three that were not were left as names. The listener's next question was whether
their existing Soulseek client on the same machine could be reached. It could: **slskd** was
running in a container beside `familiar-api`, with an HTTP API and an API key, and a shell session
drove it end to end — search, wait, read, browse the folder, enqueue — in about a dozen `curl`
calls. That is the whole feature; it just had no tool.

Two facts about slskd's API shaped the design and are not in its schema:

- **Responses are unreadable until the search completes.** `POST /api/v0/searches` returns at
  once and `responseCount` climbs within a second, but `GET /searches/{id}/responses` returns `[]`
  for as long as `isComplete` is false. slskd holds responses in memory and writes them to its
  search database when the search ends — by default a ~15 s network timeout, reported as
  `Completed, TimedOut`. Measured: 29 responses counted at 5 s, `[]` returned at 5, 10, 15 and
  20 s, 29 responses returned at 25 s. A client that reads on the first positive count gets
  nothing, every time, with no error.
- **A search returns files, not folders.** Searching `a.s.o. rain down` returned one `.flac` from a
  sharer whose folder held eleven. The folder is what a listener wants, and slskd will list it
  (`POST /users/{username}/directory`) — but nothing does that unless asked.

And one fact about this project: **Familiar is meant to be run by other people.** A tool set that
assumes a slskd on `localhost:5030` is a tool set for one installation. Most will have no Soulseek
client at all, and on those servers the tools must not exist — the "Listening Ideas" defect (`#76`)
is a surface that renders and then fails, and ADR-0022 point 3 was written to stop it recurring.

There are third-party MCP servers for slskd (`abl030/slskd-mcp` generates one from the OpenAPI
spec, 93 operations). They were considered and are recorded under Alternatives.

## Decision

1. **Familiar talks to slskd over HTTP and to nothing else.** It never speaks the Soulseek protocol,
   holds no Soulseek credentials, and runs no client. The operator runs slskd — as they already do
   if they use Soulseek at all — and gives Familiar its URL and, if slskd has one, its API key.
   Both are outbound settings in `AppSettings` (`soulseek_url`, `soulseek_api_key`,
   `app/services/app_settings.py:59`) with the usual env fallback (`SOULSEEK_URL`,
   `SOULSEEK_API_KEY`, `app/config.py:61`); the key is masked like every other outbound key.

2. **The tools are withheld until a URL is configured.** `app.mcp.server.withheld_tools()`
   (`server.py:72`) returns the Soulseek set when `has_soulseek_configured()` is false, and
   `exposed_tools()` subtracts it per `tools/list`, so configuring slskd in Settings takes effect
   on the host's next listing without a restart. This is ADR-0022 point 3 applied to tools: on a
   server with no slskd there is nothing to see, rather than four tools that answer "not
   configured" after the listener has asked. A host holding a stale listing that calls one anyway
   is told why, not "unknown tool". The tools stay in `MUSIC_TOOLS` (`tools.py:797`) so
   `ToolExecutor` dispatches them like any other; withholding is the MCP adapter's decision.

3. **Four tools, and the fourth is the reason for the set.**
   - `search_soulseek(query)` — folders, ranked, from one completed search.
   - `download_from_soulseek(username, directory)` — the whole folder, listed first.
   - `get_soulseek_transfers()` — what is moving, plus whether slskd is reachable and logged in.
   - `find_missing_on_soulseek(artist, album?)` — checks the library, and only if the answer is
     "absent" searches the network. It is the one-call form of "you don't have Lamb — here are three
     lossless copies", and its library check is what stops a model fetching an album already on
     disk. The discovery tools' guidance points at it conditionally ("if it is among your tools").

4. **A search waits for completion, then reads, then deletes.** `SoulseekService.search` polls
   `GET /searches/{id}` until `isComplete`, capped at 25 s (past slskd's own 15 s timeout, so a
   normally-ending search is read complete; a wedged one is stopped with `PUT` and read anyway),
   and then reads responses once. The search is deleted afterwards because slskd keeps every
   search until told otherwise, and a host acting on a listener's behalf would otherwise fill its
   database with queries the listener never saw.

5. **The unit is the folder, ranked lossless → free slot → matches → speed.** Responses are grouped
   by (sharer, parent directory); files whose extension is not audio are dropped, with the
   extension taken from the filename because slskd's `extension` field was blank on 22 of 35 files
   in one real search. A free upload slot outranks raw speed because a fast sharer with a queue of
   40 is slower than a modest one with a slot. `download_from_soulseek` lists the directory before
   enqueueing, so a search that matched one track downloads the album.

6. **Downloading is the listener's decision, every time.** The tool descriptions say so — confirm
   before calling, and a download lands in slskd's completed folder rather than the library — and
   the server does not enqueue on its own initiative anywhere. `find_missing_on_soulseek` searches
   and stops.

7. **Failure is an answer with a sentence.** "Nothing answered at {url}", "slskd rejected the API
   key (401)", "{url} answered, but not as slskd", "slskd is up but not logged in" — each names its
   own fix, and each is returned as `{"error": ...}` from the tool and as the status line in the
   settings panel, never raised. `status()` never raises at all. A search against a dead slskd
   raises `SoulseekUnreachable` rather than returning `[]`, for the reason `test_bandcamp.py`
   records: "nothing matched" and "this is broken" must not be the same answer.

8. **The web app configures and verifies; it does not search.** `Server → Integrations → Soulseek`
   takes the URL and key, and `GET /api/v1/soulseek/status` probes on save. Searching and
   downloading are conversational acts and belong on the MCP surface (ADR-0043); no admin screen
   grows a search box.

## Alternatives Considered

- **A third-party slskd MCP server registered beside Familiar's.** `abl030/slskd-mcp` exists and is
  a five-minute install. Rejected because the value is in the join: "you don't have this" comes
  from Familiar's library and "here it is" from slskd, and two servers cannot make one call of it.
  A host would have to search the library, search Soulseek, and reconcile by hand, at 93 operations
  of context it mostly does not need. The generated surface also exposes everything — sharing
  config, user bans, server restart — where Familiar wants four verbs.
- **Driving slskd from the host with shell calls.** This is what proved the feature. Rejected as the
  steady state for the reason the slskd-mcp README gives for its own existence: each search is
  five round-trips of JSON through the conversation, and the persistence quirk in Context is
  exactly the kind of thing a host re-discovers every session.
- **Embedding a Soulseek client in Familiar.** Rejected outright. Familiar would then hold a
  Soulseek login, share the library, accept inbound peer connections on a listener's home network,
  and own a queue and a share index — an entire second product, run for every installation whether
  or not the operator wanted it, on a server that already declines to make discovery requests
  without an off switch (ADR-0099 point 12).
- **Listing the tools always and answering "not configured".** Rejected by ADR-0022 point 3, and by
  `#76` before it. A host that sees `search_soulseek` will offer it; a listener who says yes and
  gets "not configured" has been shown a surface that cannot work.
- **Auto-detecting slskd at `localhost:5030`.** Rejected. Familiar runs in a container, where
  `localhost` is itself; the operator's slskd is on the host, another container, or another
  machine, and only they know which. A probe that happened to find something on :5030 could not
  tell slskd from anything else without the key. The URL is a setting; the probe verifies it.
- **Enqueueing the search's matched files rather than the folder.** Rejected by the measurement
  in Context: one matched file from an eleven-track folder. Listing costs one request and makes
  the download the album.
- **Ranking by upload speed.** Rejected in favour of free slot first — see point 5.

## Consequences

- **Positive:** the recommendation tools gain an ending. A host can go from "you don't have it" to
  "queued, 24-bit FLAC, sharer has a free slot" in one exchange, with the listener saying yes in
  between.
- **Positive:** nothing changes for an installation without slskd. No tool appears, no setting is
  required, no request leaves the machine.
- **Positive:** `withheld_tools()` is a seam. The next integration that exists only when configured
  goes through the same function, and `test_mcp_server.py` already pins the rule.
- **Tradeoff:** a search holds an MCP call open for 15–25 s. That is the network's pace, not
  Familiar's; the tool description says so, and `find_missing_on_soulseek` avoids it entirely when
  the library already has the album.
- **Tradeoff:** downloads land in slskd's completed folder, and Familiar does not move them — it
  never writes to the library (`docs/ZERO-TOUCH.md`). Until ADR-0117 lands, the operator's
  arrangement (a bind mount of that folder inside the library, then a sync) is what makes them
  appear; the tool says so.
- **Tradeoff:** the slskd API key sits in `settings.json` in the clear beside the others. It is an
  outbound credential to a service on the operator's own network, the same posture as the Last.fm
  and S3 keys, and ADR-0045 records why that file is not encrypted.
- **Follow-up:** closing the loop from "queued" to "in the library" is
  [ADR-0117](ADR-0117-a-soulseek-download-is-a-pending-review-track-not-a-file-move.md). As first
  written here this bullet asked for a "post-download move-and-sync"; ADR-0117 records that a move
  would break the zero-touch promise (`docs/ZERO-TOUCH.md`, commit `5fe90d7a`) and that the
  existing inbox → `PENDING_REVIEW` path already handles partial folders, tags and duplicates
  without one.
- **Follow-up:** `get_discovery_recommendations` and `get_similar_artists_in_library` could carry a
  `soulseek_available: true` field rather than relying on conditional guidance. Left out until a
  host is seen to miss the offer.
- **Follow-up:** the self-hosted slskd fork in use (`seethroughlab/slskd`, branch
  `fix/skip-size-validation-when-unknown`) and upstream 0.23 answered identically for every
  endpoint used here; if upstream changes the responses-after-completion behaviour, point 4's
  25 s cap becomes a simple wait and `test_soulseek.py::TestSearch` will say so.
