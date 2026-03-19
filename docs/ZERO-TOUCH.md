# Zero-Touch Library Plan

## Summary
Adopt a new core product principle: **Familiar never creates, modifies, moves, re-encodes, or deletes files in the user’s music library**. The library mount becomes read-only in Docker, and all enrichment stays in Familiar’s own DB/cache volumes.

This requires removing all library-mutating features, converting a few of them to DB-only behavior, and replacing today’s write-based import flow with a **read-only inbox review flow**: users place files in an incoming folder that is already part of Familiar’s read-only library paths, Familiar detects them, and the app offers the same review/adoption decisions without touching the files.

## Implementation Changes

### 1. Enforce the zero-touch runtime contract
- Make the music library mount read-only in production Docker and document that as a core install guarantee.
- Run the container itself as read-only except for explicit writable app-owned volumes/tmpfs:
  - DB/cache/config/app data
  - artwork cache
  - video cache
  - transcode/stream cache
  - temporary scratch space
- Add startup/preflight checks that fail loudly if the configured music library path is writable by the app in zero-touch mode.
### 2. Remove all music-library write paths
- Remove organizer execution entirely:
  - delete `/library/organize/run` and `/library/organize/track/{id}` execute paths
  - keep preview/reporting only if useful, but relabel as advisory output instead of actionable move operations
- Remove all tag-writing and embedded-artwork writing:
  - remove `write_to_file` / `write_to_files`
  - remove `embed_in_file` / `remove_from_file`
  - keep metadata/artwork editing as DB-only Familiar overlays
- Remove deduplicate file deletion:
  - keep duplicate detection preview
  - remove execute/delete endpoint
- Remove all in-place repair/remux/re-encode behavior from streaming:
  - no `*_in_place` audio fixes
  - always use app-owned cached transcodes/live transcodes instead
  - never update source-file hash/mtime because of playback repair
- Clamp proposed changes to DB-only:
  - remove ID3/file-move scopes from apply paths
  - keep proposed metadata changes as DB-only approvals
- Remove any frontend affordance that implies on-disk mutation:
  - organizer “run”
  - “write to file”
  - artwork embed/remove-from-file
  - destructive deduplicate execute
  - import organization/conversion controls

### 3. Replace import with a read-only inbox review flow
- Remove upload/copy-based import execution and local-path copy import.
- Replace import with an **Inbox Review** model:
  - users place files into an external incoming folder themselves
  - that folder is configured as one of Familiar’s normal read-only library paths
  - scanner discovers those files like any other path
- All newly discovered files enter `PENDING_REVIEW` status and must be approved before appearing in the main library.
- The new review dialog keeps the helpful parts of today’s import preview:
  - metadata detection
  - per-track metadata edits
  - duplicate detection and quality comparison
  - queue analysis choice
  - bulk accept/ignore decisions
- Final review actions become DB-only:
  - `accept`: make the track visible in the main library
  - `ignore`: hide/suppress it in Familiar, leave file untouched on disk
  - `prefer new` for duplicates: keep both files untouched, but mark the old track hidden/superseded in Familiar and make the new file the active visible version
- Direct zip upload import should be removed for zero-touch mode; the product promise stays cleaner if all adopted music already lives in a user-managed folder outside Familiar.

### 4. Preserve enrichment without touching files
- Track metadata editing stays supported, but only in Familiar’s DB.
- Artwork uploads become Familiar-owned overlay artwork only:
  - save to artwork cache/DB
  - never embed into source files
- Lyrics/enrichment/proposed-changes/autofill continue to work as DB overlays.
- Playback repair/transcoding should use only app-owned cache outputs, never source mutation.

### 5. Product messaging and docs
- Make zero-touch a top-level product promise in install docs, README, and Settings UI.
- Rename relevant UI surfaces so users understand the model:
  - `Import` becomes `Inbox Review` or `Review New Music`
  - `write to file` language disappears
  - organizer/deduplicate become preview/report only where retained
- Add clear copy explaining:
  - Familiar never alters your collection
  - accepted/ignored/replaced decisions affect only Familiar’s database view
  - users must manage actual file moves/tag edits with external tools

## Import Alternatives Considered
- **Recommended:** read-only incoming folder plus Inbox Review. Best match for the zero-touch promise while preserving Familiar’s strongest import UX value.
- **Possible later:** export an advisory cleanup plan for external tools. Useful, but not required for the first zero-touch release.
- **Not recommended for v1:** companion CLI importer. It weakens the simplicity of the core promise and adds another operational surface.

## Public Interfaces / Contract Changes
- Remove library-write request fields from public APIs:
  - `write_to_file`
  - `write_to_files`
  - `embed_in_file`
  - destructive organizer/deduplicate execute endpoints
  - import execution options for `format`, `organization`, and file-copy semantics
- Add read-only inbox review APIs:
  - list pending incoming tracks
  - accept/ignore/prefer-new decisions
  - bulk review actions

## Test Plan
- **Zero-touch invariant**
  - With zero-touch enabled, all library-mutating endpoints are absent or hard-fail with a clear error.
  - No request path in normal playback, metadata editing, artwork upload, duplicate review, or inbox review writes to a file under the library mount.
  - Streaming problematic files never modifies source files.
- **Docker/runtime**
  - Production compose mounts music paths read-only.
  - Container starts correctly with read-only root filesystem plus explicit writable app volumes.
  - Preflight fails if zero-touch is enabled but the library mount is writable.
- **Inbox review**
  - New files in incoming paths appear in review queue, not main library.
  - Accept makes them visible in library without moving/copying files.
  - Ignore suppresses them in Familiar only.
  - Prefer-new duplicate hides/supersedes the older DB record without deleting either file.
- **Regression**
  - DB-only metadata edits still work.
  - Artwork overlay uploads still work from cache.
  - Analysis/scanning still work against read-only library mounts.
  - Existing non-library writes (settings, caches, videos, app data, transcode cache) continue to function.

## Assumptions and Defaults
- Zero-touch means **no writes ever to files inside any user music-library path**.
- Familiar may still write to its own DB, cache, artwork, video, and transcode volumes.
- The incoming folder is part of Familiar’s configured library paths and is mounted read-only like the rest of the collection.
- The recommended replacement for import is **DB-only inbox adoption**, not server-side copy/move/import.
- The first release should prefer a simple, trustworthy promise over preserving every legacy workflow.
