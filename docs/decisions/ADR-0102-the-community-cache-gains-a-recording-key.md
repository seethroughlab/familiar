# ADR-0102: The Community Cache Gains a Recording Key

Status: accepted

Date: 2026-08-31

Extends [ADR-0101](ADR-0101-discovery-ranks-against-the-listening-model.md), whose point 6 named this
as the way past its own limit, and the community cache introduced alongside
[ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md)'s rule about where secrets live.

## Context

`ADR-0101` made discovery rank *owned* music against the listening model, and stopped at a stated
limit: an unowned record has no embedding, because there is no audio to embed. Its point 6 records
that the obstacle "is an index rather than a law", and this is that index.

### The cache already does most of this

`services/community_cache.py` shares CLAP embeddings between installations, pinned to
`laion/clap-htsat-unfused:v1` at 512 dimensions. It is live: `familiar-cache.fly.dev` by default,
and the instance on the NAS holds **21,890 embeddings and 77,770 feature rows**. The server's
`embeddings` table is keyed on `(fingerprint_hash, analysis_version, clap_model_version)` and carries
a `contributor_count`, so the shape for a shared corpus is built and running.

**It is keyed only on the SHA256 of an AcoustID fingerprint, and computing a fingerprint requires the
audio file.** So the cache can answer "here is the embedding for a track you already have", which
saves analysis time, and it structurally cannot answer "what does this record I do not own sound
like" — the lookup key cannot be produced without the thing being looked up.

That is a consequence of a deliberate privacy decision: the hash is one-way and carries no metadata.
It is a good property. It is also the property in the way.

### What a contributor can actually supply, measured

The obvious fix is for contributors to send a MusicBrainz **recording** id alongside the hash.
Measured against the production library on 2026-08-31:

| | |
|---|---|
| Active tracks | **26,434** |
| With an AcoustID fingerprint | **25,647** (97%) |
| With a `musicbrainz_track_id` | **1,787 (6.8%)** |
| With an `acoustid_lookup` payload — where the recording id comes from | **33** |

**The identifier this ADR depends on has 6.8% coverage.** A contributor could key almost nothing.
The mapping is obtainable — `acoustid_lookup` already stores
`candidates[].musicbrainz_recording_id`, and the identification path that writes it exists — but it
has been run on 33 tracks, and AcoustID is rate-limited to three requests a second, so resolving the
library is on the order of **two and a half hours of continuous lookups**.

That cost is not the objection. Not knowing it before designing the schema would have been.

### The server cannot do this for us, by construction

An obvious alternative is for the cache server to resolve recording ids itself. It cannot: it
receives a hash, not a fingerprint, so it has nothing to ask AcoustID with. The privacy design and
the discovery use case are in genuine tension, and the resolution is that **the client does the
resolving** — which is also the right place for it, since the client is the one that already holds
the audio and the AcoustID budget.

### The part that is a real change in what the cache discloses

Today the corpus is a set of opaque hashes. Nobody holding a database dump can tell what music is in
it without already having the audio to fingerprint. **Adding a recording id changes that: the corpus
becomes legible.** A MusicBrainz recording id names a recording.

This is not a disclosure about a *person* — no profile, listener or installation identifier is
attached, and `contributor_count` is a count rather than a list. It is a disclosure about the
*corpus*: "these recordings are in somebody's library". That is a smaller thing than it first sounds
and a larger thing than nothing, and it is the decision this ADR is really asking for.

## Decision

1. **The cache gains a MusicBrainz recording id as a second key.** `embeddings` keeps its
   fingerprint-hash key exactly as it is and gains an optional `recording_mbid`, so an installation
   can ask "what does recording X sound like" without holding X. Nothing about the existing lookup
   path changes.

2. **Contributors supply the recording id; the server never derives one.** It holds a hash, not a
   fingerprint, and cannot ask AcoustID anything. This keeps the one-way property that made the
   original design defensible.

3. **Contribution stays opt-in and off by default.** `community_cache_contribute` is `False` today.
   Point 5's disclosure is a reason to leave it there rather than a reason to change it: an
   installation now contributes something legible, and that should remain a decision its owner makes
   deliberately.

4. **The model pin becomes a long-term commitment, and is written down as one.**
   `CLAP_MODEL_VERSION = "laion/clap-htsat-unfused:v1"` is already in the key, which is correct.
   Vectors from different checkpoints are not comparable, so a corpus that changes pin fragments into
   islands that silently return nothing. This has been an internal detail; keyed by recording it
   becomes a promise to other installations, and changing it means a migration rather than a bump.

5. **Familiar backfills recording ids for its own library, in the background, bounded.** At 6.8%
   coverage this feature has almost nothing to key on. The resolution path exists and is rate-limited
   at three per second; it runs as a background job under `ADR-0099`'s discipline — its own health
   row, its own enable flag, resumable, and reporting progress — not as a one-shot script.

6. **A missing recording id is not an error.** Most tracks will not have one for some time, and an
   installation that never resolves any still uses the cache exactly as it does today. The feature
   degrades to what exists now rather than failing.

7. **This ADR does not decide how an unowned release is *ranked*.** That is `ADR-0101` point 6's
   question and it is harder than it looks: discovery works at release-group level, embeddings are
   per recording, and `ADR-0093` already established that averaging a group of embeddings returns the
   most generically average thing rather than a representative one. Whatever replaces the average —
   best-matching track, agreement across tracks — is a separate decision that should be made with
   this index in place and something to measure.

## Alternatives Considered

- **Key on the release-group id instead of the recording id.** Discovery is about albums, so this
  looks like the natural grain. Rejected because embeddings are per recording and there is no
  honest per-release embedding to store: `ADR-0093` recorded that averaging was tried at two scales
  and returned the library's most generically average music both times. Storing an average here would
  bake that failure into a shared corpus where it cannot be recomputed.

- **Have the cache server resolve recording ids from fingerprints.** Removes the client-side backfill
  entirely. Rejected as impossible rather than undesirable: the server receives a SHA256 hash by
  design and has nothing to send to AcoustID. Changing that would mean transmitting raw fingerprints,
  which discards the one-way property the original design was built on — a much larger concession
  than the one this ADR asks for.

- **Use Bandcamp preview clips to embed unowned music locally.** No shared corpus, no new disclosure,
  no dependency on other installations. Rejected as the weaker option and recorded in `ADR-0101`:
  it works only where a preview exists, it re-derives what somebody has already computed, and whether
  a 30-second clip embeds to a vector comparable with a full track is unknown. Worth revisiting only
  if this is declined.

- **Do nothing, and accept that discovery ranks only what you own.** Defensible. `ADR-0101` already
  delivers the larger prize — 23,683 unheard owned tracks — and unowned ranking is the smaller half.
  Rejected because the limit is arbitrary rather than principled: the vectors exist, other
  installations have already computed them, and the only thing preventing their use is a key.

- **Open the corpus to contributors outside Familiar.** Discussed and deliberately excluded from this
  ADR. It is a different product with a governance and sustainability story, and `AcousticBrainz` —
  the same idea for audio descriptors keyed to MusicBrainz, institutionally backed — stopped
  accepting submissions in 2022. Read that post-mortem before proposing it.

## Consequences

- **Positive** — the only mechanism in sight that lets Familiar rank music nobody here owns by how it
  actually sounds, rather than by what a third party says about its artist.
- **Positive** — the backfill in point 5 has value independent of this feature: recording ids improve
  deduplication, metadata correction and the identification surface, all of which currently operate
  on 6.8% coverage.
- **Positive** — nothing about the existing lookup path changes, so an installation that ignores all
  of this keeps exactly the behaviour it has.
- **Tradeoff** — **the corpus becomes legible.** Opaque hashes become named recordings. No person is
  identified and no installation is linked to a row, but "these recordings exist in somebody's
  library" becomes readable from a database dump where it was not before. This is the substance of
  the decision and should not be waved through as a schema change.
- **Tradeoff** — the model pin stops being an internal detail. Changing CLAP checkpoints becomes a
  corpus migration affecting other installations, not a version bump.
- **Tradeoff** — two and a half hours of AcoustID lookups before this installation is a useful
  contributor, and every other installation faces the same before the corpus is worth querying. The
  feature is worth little until several have paid it.
- **Follow-up** — `ADR-0101` point 6's ranking question, which point 7 above explicitly leaves open.
- **Follow-up** — whether the *features* table should gain the same key. It holds 77,770 rows against
  the embeddings' 21,890, and the same argument applies to it, but nothing in discovery reads
  features for unowned music today so it would be a capability with no caller.
- **Follow-up** — `contributor_count` is a count today. If the corpus becomes legible it is worth
  checking that it stays a count, because a list would turn a corpus disclosure into a per-installation
  one.
