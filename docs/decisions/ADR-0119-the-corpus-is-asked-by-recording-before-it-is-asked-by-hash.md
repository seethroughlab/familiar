# ADR-0119: The Corpus Is Asked by Recording Before It Is Asked by Hash

Status: proposed

Date: 2026-09-16

Implementation:
- Nothing yet. Written after reading clapback at `d07598e` (2026-09-16) beside this repository at
  `bad07ca`, not from memory — clapback's `CLAUDE.md` asks for exactly that, and this record's
  Context is the audit it asked for.

## Context

Familiar is the first client of the clapback commons and, until 2026-09-16, the only one that
mattered. Its integration was written against clapback's `ADR-0004` through `ADR-0010` and has
been correct against them since `ADR-0114` fixed the key: canonical hash, `client_id` minted on
first contribution, lookup before contribute, backoff, `pipeline_version` on every write. The
embedder is `clapback-embed` 0.1.0 from PyPI, pinned `<0.2` for the reason clapback's `ADR-0005`
gives. `ADR-0115` then named 89.4% of the library's recordings and claimed them in the corpus,
which is why the corpus reports 89.6% of its rows as named.

Between 2026-09-15 and 2026-09-16 clapback accepted six records — `ADR-0014` through `ADR-0019` —
and released `clapback-client` 0.3.0 and 0.4.0. Familiar's `community_cache.py` predates all of
them. Five of the six change nothing here: `ADR-0013` (the corpus is public data) and `ADR-0014`
(`GET /v1/pipelines`) are about the corpus; `ADR-0015`, `ADR-0016` and `ADR-0018` add batch and
identification endpoints beside the ones Familiar calls, which are kept for it. **`ADR-0019` is
the one that makes the integration wrong**, and it was accepted on a measurement.

### The key is a function of the fingerprinting path, measured

clapback's `ADR-0019`, 2026-09-16, over 56 FLACs: the `fpcalc` binary — what Familiar runs — and
pyacoustid's library path — what beets runs — return the same fingerprint string for **24 of 56**,
and for **10 of the 24** CD-quality files. Two official `fpcalc` builds from different ffmpeg
generations agree on 37. The rest differ by a few bits of ~30,000, which AcoustID's matcher
absorbs and a SHA256 cannot. The corpus key is therefore exact *within* one path and may differ
*across* two, and — the sentence clapback's client README now carries in bold — **a miss on
`lookup` does not mean the corpus lacks the recording.**

clapback's answer (`ADR-0019` point 3) is not a better hash but the identifier that is the same
on every path: *look up by recording if you hold an id, by hash otherwise, and contribute under
your hash either way.* `GET /v1/recordings/{mbid}?pipeline_version=…` returns every row any
client has claimed under that recording, one per pipeline, ordered by how many clients claimed
it and then by `contributor_count`; `Corpus.lookup(recording_mbid=)` in `clapback-client` 0.3.0+
takes the first. Agreement is now counted per recording across keys (point 2), so a second
contributor on another path confirms Familiar's vector rather than sitting beside it unrelated.

### What Familiar does today

`CommunityCacheService.lookup` (`services/community_cache.py`) takes a fingerprint and asks
`GET /v1/embeddings/{hash}` — only that. Its one caller,
`services/tasks/analysis_pipeline.py`, looks a track up at embedding time and computes locally
on a miss. `contribute` sends the hash, the vector and the pipeline identity, and never the
recording id it may hold, so the corpus learns the name of a Familiar row only when
`ADR-0115`'s backfill claims it on a later tick. The backfill receives AcoustID's own track id
with every result it resolves (`results[].id`) and discards it; `ADR-0019` point 6 admits that id
as a second claim type precisely because it survives the path differences the MBID survives.

What this costs, honestly: **today, almost nothing.** Familiar is the source of nearly every row,
so a hash miss is nearly always a true absence, and the vector it computes instead is the one
the corpus then receives. The cost arrives with the second contributor, and clapback's plug-ins
for beets (0.3.0) and Picard (0.2.0) shipped on 2026-09-16 with the batch calls and the ids.
From then on a beets install contributes under pyacoustid's key for the same recording Familiar
holds under `fpcalc`'s; Familiar on re-analysis misses it by hash and spends seconds of CPU
recomputing a vector the corpus holds, and the corpus records no agreement because Familiar
never said which recording it was contributing.

### Where the id is when it is needed

At *first* analysis a track usually has no recording id: `ADR-0115` resolves ids after analysis,
paced by AcoustID at three requests a second, and only 6.8% of the library carried one in its
tags. At *re-analysis* — an `EMBEDDING_VERSION` bump, clapback's `ADR-0006` phase 3; the
version is at 8 — **23,418 of 25,954 fingerprinted tracks hold one** (21,627 from the backfill
plus 1,791 from tags). So the recording lookup pays on re-analysis and on arrivals that
come tagged, and pays nothing on an untagged new arrival, which is looked up by hash as now.
Reordering the pipeline so that the id is resolved before the vector is computed is a different
change with AcoustID's rate limit inside the analysis path; it is considered below and not taken.

### Two smaller facts from the same audit

`docker/Dockerfile:65–69` installs `git` in the builder stage because "`clapback-embed @ git+…`
is published from the clapback repository and not yet on an index", with a note to remove the
line when it ships to PyPI. It shipped 2026-09-04; `backend/uv.lock` resolves it from
`files.pythonhosted.org` and holds **zero** `git+` sources. The comment is false and the package
is dead weight in a stage that is rebuilt on every dependency change.

`community_cache.py` is 817 lines that reimplement what `clapback-client` now ships as the
contract in code, stdlib-only and synchronous. Familiar's is `httpx` and async, which is a real
reason to keep it, but every new rule now lands in the client package first and has to be
re-derived here — this record is the first instance. Whether to adopt the package is a separate
decision (below, not decided).

## Decision

1. **`lookup` asks by recording first when it holds an id, by hash otherwise.**
   `CommunityCacheService.lookup` gains `recording_mbid: str | None = None`. Given one, it asks
   `GET /v1/recordings/{mbid}?type=musicbrainz_recording&pipeline_version=…` and takes the first
   row of `embeddings` — the server orders them by claims then contributors, the same choice
   `clapback-client` makes — and only on a 404 falls through to `GET /v1/embeddings/{hash}`.
   `pipeline_version` is sent on both, as it is today, for the reason `lookup`'s docstring
   already gives: it is the only field that makes the vector comparable with ours. The row's own
   `fingerprint_hash` is kept on `CachedEmbedding` (it may not be ours) so a caller can tell a
   cross-path hit from a hash hit; `embedding_source` in the analysis row records
   `community_cache:recording` or `community_cache:hash`, so the next re-analysis can report the
   split instead of guessing at it.

2. **The analysis pipeline passes the id it has.** `analysis_pipeline.py` reads
   `track.musicbrainz_track_id` beside the fingerprint it already reads and hands both to
   `lookup`. Nothing else in the pipeline moves: an untagged new arrival is looked up by hash,
   misses, is computed locally and contributed, exactly as today.

3. **`contribute` carries the recording id when it is held.** `recording_mbid` goes in the POST
   body beside the hash (clapback's `ADR-0012`, and what `ADR-0019` point 2's agreement join
   runs on), so a contribution from a named track is a claim in the same request and the
   per-recording comparison runs at write time rather than after the backfill's next tick. The
   backfill's `claim_recording_outcome` stays for tracks named *after* they were contributed,
   which is most of them; it is idempotent against a claim already made, and a row that arrives
   claimed simply has nothing left for it to do.

4. **The `unanswered ≠ absent` rule survives the second request.** `lookup`'s `raise_on_error`
   contract is unchanged: a recording lookup that could not be completed is not a miss and does
   not fall through to the hash, because falling through would turn "the server did not answer"
   into "the server has no row under our key" and, on the contribute path, into a duplicate
   submission — the manufactured agreement clapback's `ADR-0008` exists to avoid and its client
   README now names as the mistake two clients have made.

5. **The Dockerfile stops installing `git` for a dependency that is on PyPI.** The `git` package
   and the three lines explaining it go; `g++` stays for miniaudio. If a `git+` source ever
   returns to `uv.lock`, the build fails at resolution rather than silently, which is the
   correct place.

6. **Not decided here:**
   - **Batch lookup and contribute** (clapback `ADR-0015`, `ADR-0016`). The pipeline is
     per-track by construction — one track, one job; a whole-library pre-pass at
     `EMBEDDING_VERSION` bump time is a different shape and can be its own record when the next
     bump is planned. Point 1 is what makes such a pass worth writing.
   - **Keeping and claiming the AcoustID track id** (`ADR-0019` point 6). The backfill discards
     it today; keeping it needs a column and a decision about which id to keep when AcoustID
     returns several results for one fingerprint. Admitted, not required, and the MBID covers
     89.4% already.
   - **Resolving the recording before embedding**, so that first analysis could hit the corpus
     by id. Rejected below.
   - **Adopting `clapback-client`** in place of `community_cache.py`. A separate record: the
     async/`httpx` reason to keep the local implementation is real, and so is the maintenance
     argument against it, and neither is this record's question.

7. **Execution order:** point 5 (a deletion, no risk) → point 1 with its tests → point 2 →
   point 3 → the next re-analysis reports the `recording`/`hash` split from point 1's marker.
   Each of points 1–3 ships with a test that speaks the server's response shapes, offline, as
   `test_community_cache_contribution.py` does now; point 1's covers the 404-then-hash path and the
   unanswered-then-stop path separately.

## Alternatives Considered

- **Do nothing until a second contributor exists.** Rejected because the second contributor's
  tooling shipped the day this was written, and because the failure is silent: Familiar would
  never see it as an error, only as CPU spent and agreement not recorded. The change is small
  now and would be identical later.

- **Resolve the recording id before computing the vector**, so first analysis benefits too.
  Rejected. `ADR-0115` deliberately kept AcoustID out of the analysis path: it is a rate-limited
  external service (three requests a second, and one request hung for 47 minutes on
  2026-09-14) and the analysis queue is a place where a stall is expensive. Re-analysis and
  tagged arrivals are where the ids already are; that is most of the library and all of the
  cross-path risk for a library already named.

- **Ask by hash first and by recording on a miss.** Rejected. The hash hit is Familiar's own
  contribution and is always there for a track it has contributed; asking it first means the
  recording lookup only ever runs for tracks Familiar has *not* contributed, which are exactly
  the untagged arrivals that hold no id. The order in clapback's rule is the order that finds
  the other path's row.

- **Tolerant matching on the server.** Not Familiar's to decide; rejected there in
  `ADR-0019`'s Alternatives, with the reason (a fuzzy key is not a key).

## Consequences

- A named track on re-analysis takes another client's vector when one exists under the same
  pipeline, which is the exchange the commons exists to make; the first re-analysis after this
  reports how often that happened, and that number decides whether the batch record is worth
  writing.
- A contribution from a named track is claimed at write time; `ADR-0115`'s backfill will find
  those already claimed and say so in its health row, which should be read as the mechanism
  working rather than the backfill idling.
- One more request per named-track lookup on a miss — the recording lookup, then the hash. The
  corpus counts its limit per key, and both are cheap; the analysis path was already bounded by
  the model, not the network.
- The Docker builder stage loses a package and a lie.
- clapback's `CLAUDE.md` "Compatibility with Familiar" section lists the endpoints Familiar
  calls; `GET /v1/recordings/{mbid}` joins that list and should be added there when point 1
  ships, since the list is what protects the endpoint.
