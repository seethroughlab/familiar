# ADR-0159: Familiar No Longer Uses the Clapback Commons

Status: accepted

Date: 2026-11-02

Implementation:

- **Point 6 done 2026-11-02.** `PUT /api/v1/settings` set `community_cache_enabled` and
  `community_cache_contribute` to `false` on the maintainer's installation; both had been `true`.
  Read back through the same API.
- **Points 1–5 and 8 built 2026-11-02**, in one change:
  - `community_cache.py`, `scripts/backfill_community_cache.py`, `scripts/claim_recordings.py` and
    five test files are deleted. Both analysis phases analyse every track locally, and the
    sampled-hit helpers (`features_path`, `is_sampled_hit`, `_compute_disagreements`) went with
    the hit path they served.
  - **`canonical_fingerprint` moved, not deleted**, to `app/services/analysis.py`. The context
    above missed that the resolve phase (point 3, kept) borrowed it from the cache client to undo
    the column's hex escaping before asking AcoustID. `test_canonical_fingerprint.py` keeps its
    decode cases.
  - The settings and their route fields are gone. A `settings.json` with the four old keys
    loads, the next save drops them, and a client that still sends them gets a 200
    (`TestCommunityCacheSettingsAreGone`). `openapi.json` and `contract.lock.json` were re-locked
    at contract v1, as for `ADR-0154`'s removal, because no shipped client reads the fields.
  - The web admin's Community Cache panel became `RecordingNames.tsx`, which keeps only the
    AcoustID switch, with AcoustID's health beside it.
  - Migration `20261102_drop_claims_health_row` deletes the `community_cache_claims` row.
  - The site's home, FAQ and privacy pages no longer mention the cache, and `site/e2e/pages.spec.ts`
    checks that none does. `docs/SITE-CLAIMS.md` strikes the rows.
  - The superseded records' `Status:` lines name their points.

Supersedes [ADR-0108](ADR-0108-a-contribution-names-the-installation-that-made-it.md),
[ADR-0114](ADR-0114-a-contribution-is-keyed-on-the-fingerprint-not-the-column.md),
[ADR-0119](ADR-0119-the-corpus-is-asked-by-recording-before-it-is-asked-by-hash.md) points 1–4,
[ADR-0102](ADR-0102-the-community-cache-gains-a-recording-key.md) points 1–3,
[ADR-0115](ADR-0115-the-library-names-its-recordings-through-acoustid.md) points 6, 7 and the
claim halves of 1 and 9, and
[ADR-0144](ADR-0144-a-community-cache-hit-is-trusted-and-checked-by-sample.md) points 1–3 and 5.
Executed first among clapback's `ADR-0023` steps, which closes the commons.

## Context

clapback's `ADR-0023` (proposed 2026-11-02) closes the public commons at
`clapback.seethroughlab.com`: the instance and its DNS record are deleted, and one final CC0 export
stays published. In two months Familiar was its only contributor. The 26,401 rows it holds are
this library's vectors and features, which Familiar already keeps in `TrackAnalysis`.

**What Familiar does with the commons today, read 2026-11-02:**

- **Lookup, on by default, on every installation.** `community_cache_enabled: bool = True` and
  `community_cache_url = "https://clapback.seethroughlab.com"`
  (`backend/app/services/app_settings.py`, lines 102 and 107). Phase 1 of
  `analysis_pipeline.py` asks for features and section detail. Phase 2 asks for the embedding, by
  recording first (`ADR-0119`). A features hit skips local analysis (`ADR-0144`).
- **Contribution, opt-in** (`community_cache_contribute`, default `False`), of embeddings, features
  and analysis detail, naming the installation by a self-issued `community_cache_client_id`
  (`ADR-0108`).
- **Recording claims.** `recording_backfill`'s claim phase sends every recording id the library
  holds to the corpus every ten minutes, gated by `community_cache_contribute`, with its own health
  row, `community_cache_claims` (`ADR-0115` points 6, 7 and 9).
- **In total:** `backend/app/services/community_cache.py`, 964 lines, and 8 test files that
  reference it. ~~No client UI exposes the settings.~~ **Corrected while building:** the web
  admin did, in a Community Cache panel under Analysis → Configuration, and the public site's
  home, FAQ and privacy pages described the cache. `familiar-apple` does not generate the
  `settings` operations, so no shipped app build reads these fields.

**Familiar never depended on it.** A miss, or a lookup that did not answer, is analysed locally
(`ADR-0144` point 4), and the CLAP runtime is the `clapback-embed` package (`ADR-0105`), which
runs locally and does not touch the server. Turning the commons off costs Familiar the cache hits
and nothing else. In practice a hit is this library's own work coming back after a re-analysis.

**How it fails matters, and the code makes the slow failure the likely one.**
`community_cache.py` returns at once on `httpx.ConnectError`, but retries
`httpx.TimeoutException` up to `MAX_RETRIES = 3`, each at the client's 10-second timeout. Against
a name that still resolves to an address nobody answers on, that is about 32 seconds per lookup
and two lookups per track: roughly a minute added to a 36.6 s analysis (`ADR-0144`'s median), on every installation,
logged at `debug`. `ADR-0023` point 2 deletes the DNS record so that old installations fail fast.
This record removes the calls so the current one does not depend on that.

## Decision

1. **Familiar stops looking anything up in the commons, and stops contributing to it.** The lookup
   and contribution calls in both analysis phases, `community_cache.py`, the
   `get_community_cache_service` wiring, and their tests are removed. Every track takes the path
   that was a miss: local analysis.

2. **The settings are removed, and an old `settings.json` still loads.**
   `community_cache_enabled`, `community_cache_contribute`, `community_cache_url`,
   `community_cache_client_id` and `ensure_community_cache_client_id` go. A file holding them still
   loads, because unknown keys are ignored. That is already pinned for the `soulseek_*` keys
   (`ADR-0154`), and the same test covers these. The settings route and the OpenAPI schema lose the
   fields, and `familiar-apple` regenerates its client.

3. **`recording_backfill` keeps resolving and stops claiming.** The resolve phase, which names
   recordings through AcoustID and writes `Track.musicbrainz_track_id` (`ADR-0115` points 2 to 5
   and 8), is useful to the library by itself and stays. The claim phase, the
   `community_cache_claims` health row, and its entry in `/health/discovery-sources` are removed.

4. **Fingerprinting stays.** AcoustID identification and the resolve phase need it. Only its
   second use, as the corpus key (`ADR-0114`), goes.

5. **The data stays where it is.** `features_source` keeps its `community_cache:*` values on
   tracks that were filled from a hit, as history, and `feature_confidence` keeps what sampled hits
   recorded. No migration rewrites or drops either, because they still say truthfully where a
   value came from.

6. **The maintainer's installation is switched off now, through the settings API, before this
   is built.** Lookup and contribution are set to `false` with `PUT /api/v1/settings`. They are
   not set by editing `settings.json` in the container, the route that once lost 8,772
   declarations. This makes the last contribution known before clapback's final export is taken.

7. **`clapback-embed` is untouched** (`ADR-0105`). The package stays on PyPI and maintained, and
   `PIPELINE_VERSION` stays this library's own record of which pipeline produced its vectors.

8. **The LLM's tool description stops mentioning the community cache**
   (`backend/app/services/llm/tools.py`, the features note at line 932).

9. **Execution order:** point 6 (today, no code) → points 1–5 and 8 in one change → a release →
   clapback's `ADR-0023` takes its final export and deletes the server.

## Alternatives Considered

**Leave the code and switch the default off.** Smallest change: one `True` becomes `False`.
Rejected because it keeps 964 lines and eight test files for a server that no longer exists. It
also keeps a hardcoded hostname that a future DNS record, or a reassigned IP, could make answer
again with someone else's server, and any installation that had turned lookup on would keep
sending library hashes to it.

**Keep the integration, but with an empty URL a user can point at a self-hosted commons.**
clapback's `ADR-0023` point 7 keeps self-hosting from the export possible, so a configurable client
would let someone use it. Rejected because nobody runs one, and a client for a server nobody runs
is code that cannot be tested against anything real. A revival would be a new decision. It would
start from clapback's export and `clapback-client`, a stdlib-only package written for exactly this,
not from Familiar's older client.

**Keep lookups and drop only contribution.** Familiar would read from a frozen corpus. Rejected:
there is no server to read from, and the export is a file, not an API.

## Consequences

- **Positive:** Analysis no longer depends on a remote service in any way. Nothing on the
  analysis path waits on the network except AcoustID and MusicBrainz identification.
- **Positive:** About 1,000 lines and eight test files go, along with a setting that defaulted to
  sending fingerprint hashes from every installation to one server.
- **Tradeoff:** Re-analysing a track that the commons held now costs a full local analysis, a
  median of 36.6 s on 2026-10-02 (`ADR-0144`'s Context). `ADR-0144` expected a trusted hit to
  skip about 28 s of that; the saving was not re-measured after it was built. It matters at a
  reinstall and at a features-version bump, and only then.
- **Tradeoff:** Installations that never update keep calling the old hostname. That is safe only
  because clapback's `ADR-0023` point 2 deletes the record and does not leave it pointing anywhere.
- **Follow-up:** `CLAUDE.md`'s paragraphs on `ADR-0119` and the community cache are rewritten when
  this is built. `docs/ADR-INDEX.md` is regenerated, and each superseded record's `Status:` line
  says which points.
