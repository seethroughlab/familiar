# ADR-0115: The Library Names Its Recordings Through AcoustID

Status: accepted

Date: 2026-09-14

Implementation:
- **Accepted 2026-09-14**, the day it was proposed, as written. Building started the same day, in
  point 12's order.
- **Built 2026-09-14, points 1–10.** `services/recording_resolution.py` is point 3 as a pure
  function, tested over the probes' response shapes (`tests/test_recording_resolution.py`);
  `services/tasks/recording_backfill.py` is the two phases, with their gates, health rows, markers
  and pacing (`tests/test_recording_backfill.py`, offline — the database is a list and AcoustID a
  function); `scripts/backfill_recording_ids.py` is point 10; the job is registered in
  `background/manager.py` on `RECORDING_BACKFILL_INTERVAL_MINUTES = 10`. Two things turned out
  slightly differently: `CommunityCacheService.claim_recording` gained a sibling,
  `claim_recording_outcome`, because the boolean could not tell a 404 (recheck in six months)
  from a failed request (retry next tick); and `/health/discovery-sources` routes the two new
  rows to their own gates through `_row_enabled`, since `source_enabled` would have rendered a
  running backfill as `disabled` whenever discovery was off. The title threshold's own comment was
  corrected while writing tests: at 0.8, "The Ageing Young Rebel" does *not* match "Ageing Young
  Rebel" (3 of 4 tokens is 0.75) — the rule is what the measurement was taken at, not what a
  person would say, and the test records that.
- **Deployed and enabled 2026-09-14 02:48 UTC.** The supervised dry run first — 200 tracks, nothing
  written: **178 named (89%)**, 132 by tier 1, 8 by tier 2, 18 by tier 3, 20 by tier 4; 22 refused;
  119.8 s. Inside the band the probes predicted, so the flag went on. First tick at 02:55: 137 of
  150 named in 93 s, then 150 claims in 367 s — 24.5 a minute, zero lost — both health rows
  `working`.
- **In progress, measured 2026-09-14 11:17 UTC, 8.5 hours in.** 7,625 of the 23,853 checked: 6,851
  named, 792 refused, **89.8%** — the probes held at scale. Familiar carries **8,642** recording ids
  (from 1,791); the corpus reports **8,458 named rows**. 16,228 still to resolve, about eighteen
  hours. The final number goes here when it exists, not before.
- **Two defects, both invisible to the health surface as built, both found by looking at the
  running system rather than the test suite** — the lesson `ADR-0099` records about itself,
  learned again by a job built under its discipline. **At 12:05 UTC on 2026-09-14 one AcoustID
  request never answered.** pyacoustid's `lookup` defaults to `timeout=None`; the worker thread
  held the request for 47 minutes, `max_instances=1` skipped every tick after it, and both health
  rows read `working` throughout, because a hang is not a failure — point 10's blind spot,
  exactly. Familiar #312 (deployed 13:08): 30 s on the request, a deadline inside each phase, and
  `asyncio.wait_for` around the tick recording an overrun as `timeout` against the phase that was
  active. **From 14:30 the deadline then exposed the second:** resolve phases stopped after 4–6
  tracks with zero errors. AcoustID answered in 0.3 s from both the NAS and elsewhere, but a burst
  of MusicBrainz 503s — each retried with a blocking backoff sleep — had filled the loop's default
  thread pool, and every `to_thread` lookup waited ~45 s for a thread. The async claim phase was
  unaffected, which is what pointed at the pool. Familiar #313 (deployed 16:17): lookups run on a
  dedicated single-thread executor. First tick after: 150 considered, 134 named, 91 s. Throughput
  went 810/h → 350/h → 810/h; the two cost about five hours between them.
- **Resolution completed 2026-09-15 08:48 UTC; claims drained by 08:49.** Thirty hours from the
  flag going on, of which five were the defects above. Measured then, from the library:

  | | | |
  |---|---|---|
  | active tracks with a fingerprint | **25,954** | |
  | …checked by the job | 24,200 | |
  | …named by the job | **21,627** | **89.4%** of checked |
  | by tier — single recording | 15,202 | 70.3% |
  | by tier — title | 1,539 | 7.1% |
  | by tier — release group | 2,236 | 10.3% |
  | by tier — `sources` | 2,650 | 12.3% |
  | refused — no title match | 1,057 | 4.4% |
  | refused — no result | 885 | 3.7% |
  | refused — fingerprint known, no recording | 571 | 2.4% |
  | refused — tied / low score | 34 / 26 | 0.2% |
  | errors | **0** | |
  | **fingerprinted tracks now carrying a recording id** | **23,371 of 25,954** | **90.0%**, from 6.8% |
  | claims sent | 23,268 | |
  | claims the corpus could not take (row never contributed) | 103 | 0.4%, rechecked in 180 days |
  | **corpus rows named** | **23,196 of 25,886** | **89.6%**, from 6.8% |

  The probes said 86–91% and the run came in at 89.4%, with the tiers in the proportions they
  predicted — tier 4 a little larger than the sample suggested (12% against 6%), which is the
  "several title matches, no album match" bucket landing there as point 3 intended. The 2,573
  refusals keep their candidates; the loosened title rule the Alternatives deferred can now be
  measured offline against 1,057 real cases without a single further lookup.

Extends [ADR-0102](ADR-0102-the-community-cache-gains-a-recording-key.md), whose point 5 decided
that this installation backfills recording ids "in the background, bounded", under
[ADR-0099](ADR-0099-discovery-is-a-background-job-with-visible-sources.md)'s discipline, and left
every detail of how to this record.

## Context

`ADR-0102` was accepted on 2026-08-31 with 6.8% of the library carrying a MusicBrainz recording id.
On 2026-09-13 the cheap half shipped — `scripts/claim_recordings.py` sent the 1,748 ids the library
already held to the corpus — and on 2026-09-14 the run completed: 1,745 claimed, 3 not found, and
the corpus's 25,515 rows are **6.8% named**. Every other row is a hash nobody can resolve, which is
exactly the state clapback's `ADR-0002` point 4 said not to call "similarity search". The remaining
93% is this record.

### What is there to resolve, measured 2026-09-14

| | |
|---|---|
| Active tracks with a fingerprint | **25,607** |
| …of which without a recording id | **23,863** (23,830 distinct fingerprints) |
| …of which also with a duration | **23,853** — AcoustID needs both |
| Tracks with an `acoustid_lookup` payload from the identification feature | 33 |
| AcoustID key configured on this installation | yes |

**Nothing on the scan path writes `musicbrainz_track_id` today.** The only code that ever did was
the metadata-enrichment path shelved to a feature branch on 2026-03-06 (`7db836cd`): it took the
first AcoustID candidate scoring above 0.8 and rewrote title, artist, album, genre and year along
with the ids. The 1,791 ids the library holds are that path's residue; the count has not moved since
August because nothing has been able to move it. The lesson this record takes from that path is
that resolving an *id* and rewriting *tags* are different decisions, and only the first is made here.

### What AcoustID answers, measured 2026-09-14

`track_analysis.acoustid` holds the fingerprint and `tracks.duration_seconds` the duration, which is
all `POST /v2/lookup` needs — **no file is opened and nothing is re-fingerprinted**. The web
service's stated limit is "do not make more than 3 requests per second"; there is no batch lookup
(batching exists only for `/v2/submit`); registration gives the `client` key this installation has.

Three probes, each 200 tracks drawn at random from the unnamed 23,863, each sending the stored
fingerprint with `meta=recordings releasegroups sources`. Timing: 116–120 s per 200, so 3/s is the
ceiling in practice as well as in the documentation. The third sample:

| what came back | n | % |
|---|---|---|
| top result ≥ 0.8, **one** recording | 125 | 62.5 |
| several recordings, **exactly one** whose title matches the track's | 18 | 9.0 |
| several title matches, **exactly one** whose release group matches the album | 17 | 8.5 |
| still several, one with strictly more `sources` than the rest | 12 | 6.0 |
| several title matches, no release group matches the album | 10 | 5.0 |
| several recordings, none matching the title | 7 | 3.5 |
| a fingerprint AcoustID knows with no recording linked, or no result | 11 | 5.5 |

The second sample, classified more coarsely, agreed: 58% single-recording, 6.5% title-resolved,
21% several-with-the-same-title, 5% no title match, 8.5% nothing. Two things in those numbers
decide the design.

**The 21–27% with several recordings are mostly MusicBrainz duplicates, not different music.** A
track whose top result lists three recordings all titled "Sambatiki" is one recording that
MusicBrainz holds three times — an album entry, a compilation appearance, an unmerged submission.
The release group splits about a third of those; among what remains, `sources` (how many AcoustID
submissions carry each recording) is decisive whenever it decides at all — 3,551 against 2, 641
against 1, 2,249 against 13 — and the third sample had no ties. Picking the popular duplicate is what
Picard and beets converge on in practice, and converging matters: clapback's `ADR-0012` counts
claims per client, so two clients naming the same audio by different duplicates is two claims of
one, not agreement.

**Title matching that fails, fails on punctuation** — "Fenixfunk 5" against "Fenix Funk 5",
"YourTeethandFaceMarchingAlong)" against "Yourteethandface (Marchingalong)". That 3.5% could be
taken with a looser comparison, and this record deliberately does not: every loosening is a way to
name a track wrongly, and a wrong id is worse than none — it becomes a claim the corpus counts and a
key deduplication trusts. Ambiguous stays ambiguous, stored with its candidates, for a person or a
later rule.

### What a run costs, and why it is not a script

23,853 lookups at the 3/s ceiling is **2.2 hours of continuous requests**, and the claims that follow
are writes against the corpus's 30/minute limit — **16 hours at 25/minute** if everything resolves.
`ADR-0102` point 5 already said this is a background job and not a one-shot, and the claim run of
2026-09-13 is why: the first attempt paced *at* the write limit and silently lost 9% of its claims
to exhausted retries before anyone read the log. A job that works a bounded batch on an interval,
records its own outcome, and resumes from durable state is the shape that survives a rate-limited
window, a container restart, and a log nobody reads.

### The disclosure

The identification feature already sends a fingerprint to AcoustID when a person asks about a
track. This sends 23,853 of them without being asked, once. AcoustID receives a fingerprint and a
duration — no title, no path, no installation identifier beyond the API key. It is a smaller
disclosure than `ADR-0102`'s (which made the corpus legible) and a larger one than nothing, and
`ADR-0099` point 12's reasoning applies: a process that contacts a third party about the whole
library unprompted is a change in posture, and the owner declines it in one place.

## Decision

1. **A background job, `recording_backfill`, resolves recording ids through AcoustID and claims
   them in the corpus.** Registered in `services/background/manager.py` beside `discovery_batch`,
   on a **10-minute interval**, `max_instances=1`, `coalesce=True`. Each tick runs two bounded
   phases in order: **resolve** up to 150 tracks, then **claim** up to 150. At 3/s a resolve phase
   is about a minute; at 25/min a claim phase is six. The library resolves in about **1.1 days** and
   the claims trail by hours, at a duty cycle a rate-limited public service should not notice.

2. **Resolution sends the stored fingerprint, never the file.** `TrackAnalysis.acoustid` through
   `canonical_fingerprint` (`ADR-0114` — the column still holds two encodings) and
   `Track.duration_seconds`, to `acoustid.lookup` with `meta=recordings releasegroups sources`. A
   track with no duration is skipped and counted, not failed. The identification feature's
   `lookup_acoustid_candidates` is not reused: it takes a path and runs `fpcalc`, which is the cost
   this record exists to avoid.

3. **A recording id is accepted in four tiers, and refused otherwise.** The top result must score
   at least 0.8. Then, in order, the first rule that leaves exactly one recording decides:
   - **Tier 1** — the result lists one recording.
   - **Tier 2** — exactly one recording's title matches the track's. Match is token-set overlap
     (Jaccard) of at least 0.8 after lower-casing and stripping punctuation; no stemming, no
     transliteration, nothing that guesses.
   - **Tier 3** — among the title matches, exactly one has a release group whose title matches the
     track's album by the same rule.
   - **Tier 4** — among what tier 2 or 3 left (several, or none for tier 3), one recording has
     strictly more `sources` than every other. A tie refuses.
   A refusal stores the candidates and marks the track **ambiguous**. No fuzzier rule is added
   without a measurement showing what it would name and what it would misname.

4. **A resolved id is written to `Track.musicbrainz_track_id` — only where it is null, and nothing
   else is written.** Not title, not artist, not album: the shelved enrichment path rewrote tags
   and this record does not. An id already present is never overwritten, whatever AcoustID says.
   Provenance goes in the JSONB that already exists for it:
   `TrackAnalysis.acoustid_lookup = {"candidates": [...], "resolved": {"recording_mbid", "tier",
   "score", "at"} | null, "checked_at": ...}`, so a later reader can see which rule named a track
   and revisit one tier without touching the others.

5. **A track AcoustID cannot name is checked again after 180 days, not every tick.** AcoustID grows
   as people submit; a fingerprint it does not know today it may know next year. `checked_at` is
   the resumption state for both phases — a track is a candidate for resolution when it has a
   fingerprint, no id, and no `checked_at` within the window.

6. **The claim phase sends every id the library holds and has not yet claimed**, through
   `CommunityCacheService.claim_recording`, paced at **25/minute** — a claim is a write against the
   corpus's 30/minute limit, and the run of 2026-09-13 showed what pacing at the limit costs.
   `acoustid_lookup.claimed_at` records success and is the resumption state. **The first pass
   re-claims the 1,745 rows the script already sent** — they carry no marker — and that is accepted
   rather than seeded: the endpoint is idempotent, it costs seventy minutes once, and a marker
   written by hand would be the one row of state nothing had verified.

7. **The claim phase is gated by `community_cache_contribute`, exactly as the script was.** A claim
   tells the corpus which recordings this installation holds; that is the consent the setting asks
   for, and there is no second setting for it.

8. **Resolution is gated by its own flag, `recording_backfill_enabled`, default off.** Off means no
   fingerprint leaves the machine for this purpose; the claim phase still runs, since it sends ids
   the library already holds. On `AppSettings`, persisted the way every other flag is, edited in the
   admin UI — never by writing `settings.json` directly. It is not under `discovery_enabled`: this
   is enrichment of music you own, which `ADR-0099` scoped out of discovery by name.

9. **Two health rows, one per upstream, in `discovery_source_health`:** `acoustid` and
   `community_cache_claims`. Each records success, failure and kind, items, and backoff through the
   existing `SourceHealthRecorder`, and the job consults `should_skip` before each phase, so an
   AcoustID outage stops resolution and not claims, and vice versa. The health endpoint's
   `enabled=` for these two rows reads point 8's flag and `community_cache_contribute` rather than
   `discovery_enabled`, or a disabled discovery would render a running backfill as `disabled`.
   `ADR-0099` point 9 applies per track: one track's exception is recorded, the session rolled
   back, the batch continues.

10. **A script wraps the same function for the supervised first run.**
    `scripts/backfill_recording_ids.py --limit N --dry-run`, in the shape `claim_recordings.py`
    set: it calls the job's phase functions with a limit and reports the tally. The first real
    run is `--limit 200` under a person's eye; the flag is turned on after the numbers match the
    probes.

11. **Not decided here.** What Familiar's deduplication and metadata surfaces do with 20,000 new
    ids — nothing reads the column today except export. Whether MusicBrainz duplicates should be
    reported upstream. Anything on the corpus side, which `ADR-0012` owns. And `ADR-0102` point 7's
    ranking question, still open.

12. **Execution order:** the settings flag and health wiring; the tier logic as a pure function
    with tests over recorded AcoustID responses (the probes' shapes, offline); the two phase
    functions and the script; the scheduler registration; a supervised `--limit 200` run compared
    against the probes; enable; then this record's Implementation block carries the coverage
    number the whole thing was for.

## Alternatives Considered

- **A one-shot script, like `claim_recordings.py`.** Simplest, and how the cheap half shipped.
  Rejected because `ADR-0102` point 5 already decided against it, and the claim run demonstrated
  why: 2.2 hours at a ceiling with no resumption is a run that is restarted from the top when it
  fails, and a script pacing at a limit lost 9% silently. The script survives as point 10's
  supervised entry to the same code.

- **Resolve through MusicBrainz search on title and artist instead of AcoustID.** Needs no
  fingerprint disclosure. Rejected because it is text matching at one request a second against a
  service that already throttles the discovery batch, and because it names a *recording* by its
  tags rather than its audio — precisely the class of wrong id this record refuses in tier 2.
  AcoustID is content-addressed; that is the whole reason the corpus keys on it.

- **Claim from `acoustid_lookup` without writing `Track.musicbrainz_track_id`.** Leaves the
  library's tags untouched and the disclosure decision cleaner. Rejected because `ADR-0102` point 5
  and its consequences intend the library to hold the ids — deduplication and identification were
  named as beneficiaries — and because two sources of truth for one id is how the 1,791 became a
  number nothing could move. Point 4 writes the id and only the id, which is the narrow version of
  this.

- **Claim every candidate when the tiers cannot choose.** Lets the corpus's per-client counting
  sort it out. Rejected: a claim is an assertion the corpus counts (`ADR-0012`), and one client
  asserting three ids for one hash is noise dressed as evidence. The corpus would derive a
  recording by id-text order, which is a coin toss with a straight face.

- **Take the first candidate above 0.8, as the shelved enrichment path did.** Resolves the 3.5%
  no-title-match and the tied cases too. Rejected because the measurement shows what "first" means
  in that bucket — "Gratis" for "Gratis - Pedro Vs. Prefuse.", "10 Dollar" for "10" — and a wrong
  id is a claim the corpus counts and a key deduplication trusts. The cost of refusing is 3.5%
  coverage; the cost of accepting is silent.

- **Loosen the title rule to catch punctuation and spacing.** Would take most of the 3.5%.
  Deferred rather than rejected: point 3 allows it after a measurement of what it names and
  misnames, and the ambiguous rows keep their candidates so the measurement can be made offline
  without another 23,000 lookups.

## Consequences

- **Positive** — the library goes from 6.8% to an expected **86–91%** of fingerprinted tracks
  carrying a recording id, and the corpus's coverage follows: its similarity results become
  resolvable for most of what it holds, which is the state four of clapback's accepted records
  have been waiting for.
- **Positive** — no file is opened. The whole backfill is 23,853 HTTP requests carrying data the
  database already holds, at a rate a public service documents as acceptable.
- **Positive** — every named track records which rule named it. Tier 4 is the one most worth
  revisiting, and it can be revisited alone.
- **Tradeoff** — 23,853 fingerprints leave the machine for AcoustID, once, under a flag that is off
  until the owner turns it on.
- **Tradeoff** — tier 4 picks the popular MusicBrainz duplicate, which is a judgement about which
  of several true ids to assert, not a fact. It is recorded as tier 4 so it can be told apart.
- **Tradeoff** — the first claim pass spends seventy minutes re-claiming 1,745 rows the script
  already sent, by point 6's choice.
- **Tradeoff** — about 3.5% of tracks stay unnamed by rule, with their candidates stored; a person
  or a later measured rule can take them.
- **Follow-up** — point 11's consumers: deduplication and identification have a column they can
  read now, and nothing reads it.
- **Follow-up** — the loosened title rule, measured offline against the stored candidates.
- **Follow-up** — the coverage number after the run, dated, in this record's Implementation block,
  and `ADR-0102`'s updated to say point 5 is built.
