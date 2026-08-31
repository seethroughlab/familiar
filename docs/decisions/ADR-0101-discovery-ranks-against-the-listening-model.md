# ADR-0101: Discovery Ranks Against the Listening Model

Status: accepted

Date: 2026-08-31

Extends [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md), whose premise is that one
ranking engine serves every surface that has to choose music, and
[ADR-0093](ADR-0093-collections-suggest-tracks-from-the-library.md), which built the mechanism this
ADR points at a new collection. Consumes [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)'s
event stream, which discovery does not currently read.

## Context

Discovery is the one thing Familiar cannot buy from a streaming service. Spotify's advantage is
collaborative filtering across hundreds of millions of listeners; Familiar will never have that, and
building a worse version of it is not a strategy. What Familiar has instead is a far deeper model of
*one* listener: the audio itself, every play, and every skip.

**None of that reaches discovery today.** Measured against the production library on 2026-08-31:

| | |
|---|---|
| Tracks with a CLAP embedding | **26,471** |
| `play_events` (ADR-0004), of which skips | **2,364** / **1,066** |
| Artists with a cached Last.fm similarity | 3,553 |
| Discovery services referencing `PlayEvent` | **none** |

`PlayEvent` appears in neither `recommendations.py`, `new_releases.py`, nor `library_discover.py`.
An unowned album's `match_score` comes entirely from Last.fm's own `match` string
(`recommendations.py:177`), which is a fact about Last.fm's listeners rather than about this one.
`ADR-0004` was executed early and deliberately — its place in the execution order was justified by
"skip/completion events accumulate during the months of native work — the recommender is otherwise
cold at launch". The data is now warm. Discovery does not read it.

### What discovery currently answers

*"Did an artist I already play put out something new?"* — a release radar. It works, and after
`ADR-0099`'s Phase 0 and Phase 1 it works quickly, but **106 distinct artists** have ever produced a
find. Two of the three surfaces built on the same table produce almost nothing:
`listening_profile_recommendation` holds **26 rows** and `playlist_recommendation` holds **0**. No
listener has ever dismissed a discovery, so there is no negative feedback on this surface at all.

### The largest opportunity is the library already on disk

| | |
|---|---|
| Active tracks | **26,434** |
| Ever played | 2,751 |
| **Never played** | **23,683 (90%)** |
| Artists owned but never played | **2,614 of 3,453 (76%)** |

Ninety percent of this library has never been heard through Familiar. **This is the one discovery
problem where owning the files is the advantage** — a streaming service cannot recommend from a
collection it cannot see, and cannot know that you bought something in 2014 and never played it.
Today it is served by `unheard_tracks` and `deep_cuts`, two lists on the Discover dashboard ordered
by play count. Play count is not taste; it is the absence of taste data.

### The engine already exists, twice, and this is not a request to build one

`ADR-0005`'s ranking engine already weights exactly the signals this ADR wants. `RankingProfile`
carries an `embedding` weight (0.15 ambient, 0.35 radio), a `taste_weight` over play count, recency
and favourites, and a `skip_penalty` whose comment reads *"from ADR-0004 `PlayEvent`. Rejection is
weighted more heavily: skipping is ambiguous"*. Radio uses all of it. Discovery uses none of it.

`get_candidates` cannot serve rediscovery unchanged, because it takes a `current_track_id` and
answers "more like this one". But `ADR-0093` already built the collection-shaped form:
`suggest_for_collection(seed_track_ids, exclude_track_ids, profile_id)` takes a set of tracks, finds
what several of them independently reach, excludes what the listener already has, demotes what they
have rejected, and returns each suggestion with the seed that pulled it in.

### A premise this ADR nearly got wrong

The obvious design — "rank unheard tracks against the listener's taste centroid" — was drafted here
and is **wrong**, and `ADR-0093` had already found out why. Its module docstring records the finding
in the code that superseded it:

> Averaging a collection's embeddings was tried at two scales and failed the same way both times. A
> mean over all 1,730 favourites returns the library's most generically average music; k-means into
> four clusters and a mean of each only moves the problem down a level, because a cluster of 200
> tracks still has a centroid that no track occupies and nothing truthful to call it.

A centroid over 2,751 played tracks would fail harder than a centroid over 1,730 favourites, for the
same reason and at a larger scale. **Agreement between seeds, not their average**, is the settled
answer, and it carries a second property this ADR needs: it can say *why*.

## Decision

1. **Discovery ranks candidates with the engine that already ranks playback**, rather than with a
   score borrowed from an external service or with play count. `ADR-0005`'s premise is that one
   ranking engine serves every surface that chooses music; discovery is such a surface and has been
   an exception to that by omission rather than by decision.

2. **Rediscovery is the first application, and it is `ADR-0093`'s mechanism with a different
   collection.** Seeds are what the listener actually plays; the exclusion set is everything they
   have already played; the result is owned, unheard tracks ranked by agreement with their real
   listening. No new ranking code, and no centroid.

3. **Every suggestion carries its reason, and the reason is a real pair of tracks.** `ADR-0093`
   point 3's rule holds here for the same reason it held there: three attempts at naming a cluster
   failed, and "because you play *X*" is both true and checkable where a generated label is neither.

4. **The skip signal is negative evidence for discovery, not only for playback.** 1,066 skips exist
   and `_demote_rejected` already consumes rejections for suggestions. An artist whose tracks a
   listener consistently skips should not have their new release promoted, and today it is promoted
   identically to any other.

5. **Rediscovery is a section of `/library/discover`, not a new destination.** Discover is the
   discovery surface, and a parallel "find music" destination beside it splits the one question a
   listener is asking. This replaces `unheard_tracks` and `deep_cuts` in place rather than joining
   them.

6. **Unowned candidates are not ranked on audio *yet*, and the obstacle is an index rather than a
   law.** There is no embedding for a record that is not on disk. What the listening model can do
   for external candidates today is choose better *seeds* and demote artists the listener skips —
   real improvements, but not ranking an unheard album by how it sounds.

   **The community cache is the path to that, and it is closer than it looks.**
   `services/community_cache.py` already shares CLAP embeddings between installations, pinned to
   `CLAP_MODEL_VERSION = "laion/clap-htsat-unfused:v1"` at 512 dimensions, opt-in and hashed. It is
   keyed *solely* on the SHA256 of an AcoustID fingerprint — and computing a fingerprint requires the
   audio file. So it accelerates analysis of music you own and structurally cannot answer "what does
   this record I do not own sound like", because the lookup key cannot be produced without the thing
   being looked up.

   That is a consequence of a privacy decision worth keeping: the hash is one-way and carries no
   metadata. **Adding a MusicBrainz recording id as a second key would lift the limit without
   weakening it** — contributors already resolve MBIDs, and an embedding is derived data rather than
   a reproduction, so 512 floats keyed to a recording share nothing a fingerprint hash does not.
   Scoped as a follow-up, not decided here.

7. **A discovery surface that returns nothing is a defect, and is reported as one.** Two of the three
   external surfaces return 0 and 26 rows. `ADR-0099` point 8 requires a source that has never
   succeeded to say so; the same rule applies to a *surface* that never produces, which is presently
   indistinguishable from a library with nothing to find.

## Alternatives Considered

- **Rank unheard tracks against a taste centroid over play history.** The first draft of this ADR.
  Rejected on `ADR-0093`'s evidence, quoted in full above: averaging embeddings was tried at two
  scales and returned the library's most generically average music both times. Scaling the same
  mistake from 1,730 favourites to 2,751 played tracks would not fix it, and a centroid cannot say
  why a track was chosen.

- **Build a discovery-specific scorer, separate from the playback ranker.** Tempting because
  discovery's inputs differ — no "current track", a much larger pool. Rejected because it directly
  contradicts `ADR-0005`, and because the weights that matter (embedding, taste, skip penalty) are
  the same ones; two scorers would mean two sets of numbers to tune with a listener's attention as
  the only test, and `ADR-0005` already says those numbers cannot be guessed twice.

- **Compete with Spotify on collaborative filtering, using the community analysis cache.** The cache
  exists and aggregates across installations. Rejected as a strategy: the population is orders of
  magnitude too small to produce Discover Weekly, and the attempt would trade Familiar's actual
  advantage — total knowledge of one listener and their files — for a weak version of somebody
  else's. It may still be worth having as a *tiebreak* signal; it is not worth building the surface
  around.

- **Fix the surfaces that return nothing first, and leave ranking alone.** Cheaper, and 0 rows in
  `playlist_recommendation` is plainly a bug. Rejected as the *decision* because it treats the
  symptom: those surfaces would then return externally-scored candidates, which is the thing this
  ADR says is not good enough. The bug should be fixed regardless, and does not need an ADR.

- **Leave rediscovery ordered by play count.** It ships today and is not wrong, only shallow.
  Rejected because 90% of the library has never been played, so play count orders almost the entire
  candidate set by the same value — zero. The ranking it appears to apply is, for the set that
  matters most, no ranking at all.

## Consequences

- **Positive** — the deepest signal Familiar has starts reaching the surface where it is worth the
  most. 26,471 embeddings and 1,066 skips currently inform playback and nothing else.
- **Positive** — the largest untouched opportunity, 23,683 unheard owned tracks, becomes addressable
  with mechanisms that already exist and have already shipped once.
- **Positive** — it puts Familiar's discovery on the axis it can win, rather than the one it cannot.
  A streaming service cannot rank a collection it cannot see.
- **Tradeoff** — `suggest_for_collection` was built and tuned for collections of tens to low
  thousands. Play history is 2,751 tracks and the exclusion set is the same size; `SEED_SAMPLE_CAP`
  and `hnsw.ef_search` behaviour at that scale are assumptions this ADR inherits rather than
  verifies. `ADR-0093`'s own history — a `POOL_SIZE` of 400 silently returning 40 rows — is the
  reason to measure rather than assume.
- **Tradeoff** — external discovery improves less than rediscovery does, because point 6's limit is
  real. Anyone reading this expecting all of discovery to get better should read that point.
- **Follow-up** — **the rotation gate is a bug and is not fixed here.**
  `get_prioritized_artists_batch` selects `FROM ProfilePlayHistory`, so the 2,614 artists owned but
  never played are structurally invisible to new-release discovery. Nothing in `ADR-0099` asks for
  that; it is an implementation accident, and the fix is ordinary work. It is named here because
  `ADR-0099`'s Phase 2 planned to delete `run_new_releases_check`, the only path that covers all
  3,453 artists, which would have made the gap permanent.
- **Follow-up** — **a MusicBrainz-keyed index on the community cache is the highest-value item this
  audit turned up, and it is not part of this ADR.** The cache is live: `familiar-cache.fly.dev` by
  default, and the instance on the NAS holds 21,890 embeddings and 77,770 feature rows. Keyed by
  MBID as well as by fingerprint hash, it would let point 6 rank unowned records by sound using
  vectors other installations already computed — which is the only mechanism in sight that gets
  Familiar to audio-native discovery of music nobody here owns. It needs its own ADR: it changes a
  privacy-relevant schema, and the model pin becomes a long-term commitment rather than an internal
  detail, because vectors from different CLAP checkpoints are not comparable.
- **Follow-up** — a preview-audio path (Bandcamp serves clips, and is already integrated) is the
  fallback if the cache route is rejected. Whether a 30-second preview embeds to a vector comparable
  with a full track is unknown, and that is the question to answer before building on it. It is the
  weaker option: it works only where a preview exists, and it re-derives what somebody has already
  computed.
- **Follow-up** — whether the cache should ever accept contributions from outside Familiar is a
  strategic question this ADR deliberately does not open. `AcousticBrainz` is the precedent worth
  reading first: the same idea for audio descriptors keyed to MusicBrainz, institutionally backed,
  and it stopped accepting submissions in 2022.
- **Follow-up** — a listener has never dismissed a discovery. Whether that is because the surface is
  unused or because the affordance is not reachable is unresolved, and the answer changes how much
  point 4's negative signal is worth on external candidates.
