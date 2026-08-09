# ADR-0048: Seeded Playlists Are Generated From Analysis, Not From a Sentence

Status: proposed

Date: 2026-08-09

Extends [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md)

## Context

[ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md) point 5 retires the chat clients. Point 6
names one thing that dies with them — "Listening Ideas" — and rules that an affordance whose
destination is not mounted must not survive its destination, citing `familiar` #70, #74 and #76.

**Point 6 enumerated one affordance and there are seven.** Verified at write time,
`useUIStore.getState().triggerChat(...)` has these callers:

| Site | What the listener sees | What it sends |
|---|---|---|
| `Library/ArtistDetail.tsx:852` | album context menu → "Make a playlist" | *"Make me a playlist based on the album X by Y"* |
| `Library/browsers/AlbumGrid.tsx:628` | album context menu → "Make a playlist" | same |
| `FullPlayer/FullPlayer.tsx:513` | track context menu → "Make a playlist" | *"Make me a playlist based on 'T' by A"* |
| `Library/browsers/VibeMap/VibeMap.tsx:541` | map selection → "Create a playlist" | *"Create a playlist from these artists: …"* |
| `Home/HomeScreen.tsx:230` | prompt cards | the card's text |
| `Home/HomeScreen.tsx:580` | "Help me rediscover my library" | that sentence |
| `Discovery/CuratedPrompts.tsx:54` | Listening Ideas | the prompt |

**Four of the seven are one feature.** "Make me a playlist based on this album / this track / these
artists" is a real capability that happens to be *implemented* by composing an English sentence and
handing it to a language model. The sentence is an implementation detail of a button whose meaning
is already unambiguous — the listener has already told us the seed by right-clicking it.

**The remaining three are genuinely conversational** and have no non-chat meaning. "Help me
rediscover my library" is a request for a conversation, not a computation with a defined output.

**Familiar already holds everything this needs, and it is not the language model.** The
tracks are analysed: CLAP embeddings in pgvector, and typed feature columns on `TrackAnalysis`.
`services/ambient.py:586`'s `get_candidates` fetches a top-150 pool by embedding distance and scores
it in Python against a `RankingProfile` (`services/ranking_profiles.py`) weighted across key, energy,
embedding, vocal, brightness, valence and dynamic range, with taste and negative signal from
`PlayEvent`. `_select_diverse_tracks` (`handlers/playlists.py:166`) already enforces a
`max_per_artist` constraint. **The model was never the thing that knew which tracks sound alike —
the analysis was.** The model was reading a sentence and choosing which of these to call.

**The one thing the model did that nothing replaces is interpretation**, and for these four sites
there is nothing to interpret.

**A contradiction inside ADR-0043 forces part of this now.** Point 5 keeps the provider layer
*because* `library_discover.py:197` is a second consumer of `complete_utility`; point 6 deletes the
endpoint that line lives in. Those are the only two callers of `get_provider()`, so executing both
points as written leaves `providers.py`, `providers_anthropic.py`, `providers_openai.py`,
`models.py` and the `anthropic`/`openai` dependencies dead. Accepted deliberately on 2026-08-09:
**Familiar calls no model itself.** That is ADR-0043's argument carried to its conclusion — the host
brings the model — and it means this ADR's feature cannot be built by quietly calling an LLM
server-side.

**Playlist naming is already not a model's job**, which is easy to assume otherwise.
`executor.py:144`'s `_playlist_name_from_request` strips filler words from the typed sentence. It
takes `self.user_message`, which a button does not have, so seeded generation needs its own naming
rule rather than inheriting one.

**No seeded generator exists to extend.** `playlists/recommendations.py` is Last.fm and Bandcamp
lookups for artists and albums *not* in the library — a different feature that answers "what should
I buy", not "what should I hear".

## Decision

1. **A seeded playlist is a first-class server capability, not a chat transcript.** One endpoint,
   `POST /api/v1/playlists/generate`, takes a seed and returns a playlist. The four surviving
   affordances call it directly. **No English sentence is constructed anywhere in the client**, which
   is what makes the button independent of whether any language model exists.

2. **The seed is structured and closed.** Exactly one of `track_id`, `album` (artist + name),
   `artist`, or `track_ids` (an explicit set, which is what VibeMap has). A free-text seed is
   deliberately not accepted: it would re-introduce interpretation, and interpretation is the thing
   that needs a model.

3. **The pipeline is: seed → pool → score → constrain → order → name**, each stage reusing what
   exists. The pool is `get_candidates`' pgvector search widened for playlist-sized output; scoring
   is a `RankingProfile`; the constraint is `max_per_artist`; ordering and naming are new and small.
   **A multi-track seed is a centroid of its embeddings**, not a loop over seeds, so "these artists"
   is one query rather than N.

4. **A new `PLAYLIST` ranking profile, because `RADIO` and `AMBIENT` are tuned for the wrong
   question.** Both exist to choose what plays *next* — `AmbientCandidate` carries
   `key_compatibility`, `suggested_start_pct` and `suggested_end_pct`, which are mixing concerns.
   A standalone playlist is judged as a set, not as a sequence of transitions. Reusing `RADIO`
   because it is nearby is how a feature ends up subtly wrong in a way nobody can name.

5. **The seed material is excluded from the result by default**, with `include_seed` to opt in.
   "A playlist based on this album" that opens with that album has answered a question nobody asked;
   the listener already has the album, and reached for this to leave it.

6. **Generation returns a saved playlist, not a preview.** It is reached from a context menu that
   said "Make a playlist", and a preview step would make the button a lie. It is marked
   `is_auto_generated` so it sorts and filters with the others, and deleting it is one action.

7. **Names are deterministic and say what the seed was** — "Based on *OK Computer*", "Like *Cocteau
   Twins*" — never a timestamp. `AI Playlist — Aug 09` was acceptable when a sentence had already
   described the intent somewhere the listener could see; a button leaves no such record.

8. **It is an MCP tool as well as an endpoint.** `generate_playlist` joins `MUSIC_TOOLS`, so a host
   can do what the button does. Everything the retired chat could do for these four sites, an MCP
   host can still do — which is what makes the retirement a move rather than a loss.

9. **The three conversational affordances are removed, not replaced.** Home's prompt cards, "Help me
   rediscover my library" and Listening Ideas are requests for a conversation. Rebuilding them
   without one would be inventing a feature to fill a hole, and ADR-0043 point 6 already ruled that
   reinstating prompts for an external host is a separate product decision.

## Alternatives Considered

**Point the four buttons at `get_radio_suggestions` and ship it in an afternoon.** It is already
built, already returns scored neighbours, and demonstrably produces good results — seeded from
Cocteau Twins it returned Beach House and Autumn's Grey Solace. Rejected because it answers a
different question well rather than this question adequately: its scores are transition
compatibility, it has no artist-diversity constraint, and it takes exactly one track as a seed, so
albums and artist sets would need a representative track chosen arbitrarily. This was the first
proposal in the session and was rejected on review, correctly — reaching for the nearest existing
engine is how "make a playlist from this album" becomes "radio, but it stops after 20".

**Delete all seven affordances and let MCP be the only way.** Smallest diff, perfectly consistent
with ADR-0043, and no new backend surface. Rejected because it makes the app strictly worse at
something it does today for anyone not running an MCP host, and because "right-click an album →
make a playlist" is a better interaction than typing a sentence about the album you just
right-clicked. ADR-0043 replaced Familiar's *chat client*; it did not argue that Familiar should
stop having features.

**Keep the chat client alive just for these buttons.** Preserves everything with no new work.
Rejected: it keeps 2,092 backend lines, both provider SDKs, the API key setting and the whole
conversational surface alive to serve four context-menu items, and it contradicts ADR-0043's
accepted rationale.

**Generate the playlist server-side with an LLM call.** A small `complete_utility` prompt could pick
tracks from a candidate list and name the result. Rejected because the provider layer is being
deleted by decision on the same day, and because it is strictly worse than the analysis: the model
would be choosing from a list the embeddings already ranked, adding latency, cost and
non-determinism to reorder its own input.

**Make it a smart playlist rule instead.** `SmartPlaylistService` already stores rules and
re-evaluates them. Rejected because a seeded playlist is a snapshot the listener expects to stay
put, and a rule that re-evaluated would silently change a playlist they had shared or downloaded.
Seeded generation and smart rules are different promises.

## Consequences

- **Positive.** "Make a playlist" survives the chat retirement, gets faster, costs nothing per use,
  and works with no API key configured — on a server that, after ADR-0043 point 5, has no model.
- **Positive.** The capability becomes reachable from an MCP host and from the app through one
  implementation, so they cannot drift.
- **Positive.** It uses the analysis Familiar spends hours computing. The embeddings and features
  currently serve radio and the map; this is a third consumer, and it is the one listeners asked for
  by right-clicking.
- **Tradeoff.** A new ranking profile is a new thing to tune, and it will be wrong at first. `RADIO`
  and `AMBIENT` took iteration; this will too, and it needs listening rather than tests.
- **Tradeoff.** Deterministic naming is duller than what a model wrote. "Based on *OK Computer*" is
  honest and repetitive where the chat occasionally produced something delightful.
- **Tradeoff.** Three affordances are removed with nothing in their place, and Home loses visible
  surface area. That is the correct outcome for a conversational feature on a server with no
  conversation, but it is a loss and should not be described otherwise.
- **Follow-up.** VibeMap's seed is an artist set, which is the least-tested path — artist-level
  embeddings are a centroid of a centroid, and the result may be mush. Worth checking before the
  map's button is re-pointed rather than after.
- **Follow-up.** `library_discover.py`'s `get_curated_prompts` is deleted by ADR-0043 point 6, which
  takes `get_provider()`'s last caller with it. Removing the provider layer, both SDK dependencies
  and the AI settings surface is part of executing that, and is recorded here because this ADR is
  what makes the removal safe — nothing this feature does needs them.
