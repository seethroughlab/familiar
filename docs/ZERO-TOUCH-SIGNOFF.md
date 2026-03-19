**Zero-Touch + Review Queue Signoff Checklist**

**Release Blockers**
- [ ] Make production music-library mounts read-only in [docker-compose.prod.yml](/Users/jeff/Developer/familiar/docker/docker-compose.prod.yml#L83).
- [ ] Update install docs to stop telling users to mount `/music` as `:rw` in [INSTALLATION.md](/Users/jeff/Developer/familiar/docs/INSTALLATION.md#L133) and [INSTALLATION.md](/Users/jeff/Developer/familiar/docs/INSTALLATION.md#L320).
- [ ] Add runtime/preflight enforcement for the zero-touch promise:
  - fail or warn loudly if configured library path is writable
  - ideally add readonly-rootfs support plus explicit writable app-owned volumes
- [ ] Fix pending-review API client paths in [pendingTracks.ts](/Users/jeff/Developer/familiar/packages/frontend/src/api/pendingTracks.ts#L97) to avoid `/api/v1/api/v1/...`.
- [ ] Verify Pending Review UI actually loads and actions work end-to-end after the API-path fix.

**Feature-Completeness Gaps**
- [ ] Decide whether the docs should promise:
  - `all newly discovered files go to review`, or
  - `only incoming-path files go to review`
- [ ] Align [ZERO-TOUCH.md](/Users/jeff/Developer/familiar/docs/ZERO-TOUCH.md#L46), [TRACK-REVIEW-QUEUE.md](/Users/jeff/Developer/familiar/docs/TRACK-REVIEW-QUEUE.md#L5), and scanner behavior in [scanner.py](/Users/jeff/Developer/familiar/backend/app/services/scanner.py#L458).
- [ ] Either implement the missing Pending Review controls promised in docs:
  - group metadata edit
  - per-track metadata edit
  - global skip-all
  - queue-analysis toggle
- [ ] Or trim the docs so they match the current shipped UI exactly.

**Contract Cleanup**
- [ ] Remove the remaining `embed_in_file` API surface from [metadata.ts](/Users/jeff/Developer/familiar/packages/frontend/src/api/metadata.ts#L109).
- [ ] Confirm backend no longer accepts or needs any lingering write-oriented query params/fields.
- [ ] Sweep docs for stale “imports require write access” language, including [dependencies.md](/Users/jeff/Developer/familiar/docs/dependencies.md#L384).

**Validation**
- [ ] Add backend tests for zero-touch invariants:
  - removed endpoints return 404/absent
  - metadata/artwork flows stay DB/cache-only
  - streaming/transcode never mutates source files
- [ ] Add frontend/integration tests for Pending Review:
  - browser loads
  - approve/skip/replace work
  - pending tracks do not appear in main library
- [ ] Run one manual end-to-end check:
  - add new files
  - see them in Pending Review
  - approve/skip/replace
  - confirm no writes occur under the library mount

**Signoff Rule**
- [ ] Only call this complete when:
  - deployment is truly read-only for the library
  - docs match shipped behavior
  - Pending Review works end-to-end
  - zero-touch is enforced, not just intended

If you want, I can take this checklist and turn it into a new doc in `docs/` so we can track it as we close items.