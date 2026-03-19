# Pending Track Review Queue

## Context

Currently the library scanner discovers new audio files and immediately adds them as ACTIVE tracks. This bypasses user control — the user has no opportunity to review metadata, handle duplicates, or decide whether a track belongs in their library.

This feature changes the scanner so newly discovered tracks enter a `PENDING_REVIEW` state. The user reviews them in a queue UI where they can edit metadata, handle duplicates with quality comparison, and approve/skip tracks — the same choices previously available in the (now-deleted) import dialog, minus transcode and file organization (zero-touch).

### Import Groups

Pending tracks are presented **grouped by immediate parent folder**, not as a flat list. If a user adds 10 album folders with ~15 tracks each, the review queue shows 10 collapsible groups — not 150 individual tracks. Each group has its own bulk actions (import all, skip all, edit shared metadata, replace upgrades, skip downgrades). Groups with zero duplicates get a one-click "Import All" for fast approval.

## Step 1: Database Schema

### 1a. Add enum values to `TrackStatus` in `backend/app/db/models/base.py`

```python
PENDING_REVIEW = "pending_review"  # Newly discovered, awaiting user review
SKIPPED = "skipped"                # User chose to permanently ignore this file
```

### 1b. Add `review_info` JSONB column to Track in `backend/app/db/models/tracks.py`

```python
review_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

Populated when `status=PENDING_REVIEW`, null otherwise. Shape:
```json
{
  "duplicate_of": "uuid | null",
  "duplicate_info": "Artist - Album - Title",
  "duplicate_match_type": "exact | normalized | artist_title | null",
  "trump_status": "trumps | trumped_by | equal | null",
  "trump_reason": "FLAC 16-bit 44.1kHz > 320kbps CBR",
  "incoming_quality": { "format_tier": 4, "format_tier_name": "...", ... },
  "existing_quality": { "format_tier": 3, ... }
}
```

### 1c. Migration: `backend/migrations/versions/20260319_pending_review_status.py`

- `ALTER TYPE trackstatus ADD VALUE 'pending_review'`
- `ALTER TYPE trackstatus ADD VALUE 'skipped'`
- Add `review_info` JSONB column to `tracks`
- Partial index: `CREATE INDEX ix_tracks_pending_review ON tracks (created_at) WHERE status = 'pending_review'`
- Downgrade: drop column + index only (PG enum values can't be removed)

## Step 2: Extract Duplicate Detection Service

### New file: `backend/app/services/duplicate_detection.py`

Move `_find_import_duplicate` and `_enrich_tracks_with_duplicates` from `backend/app/api/routes/library_import/preview.py` into this shared service. The preview route will import from here instead.

Key change: add `Track.status == TrackStatus.ACTIVE` filter to all duplicate queries so PENDING_REVIEW and SKIPPED tracks aren't matched as duplicates.

New function for scanner use:
```python
async def detect_duplicate_for_track(
    db: AsyncSession,
    track: Track,
) -> dict[str, Any] | None:
    """Run duplicate detection for a track, returning review_info dict or None."""
```

Uses existing `_find_import_duplicate` + `calculate_quality_score` + `compare_quality` from `backend/app/services/quality.py`.

## Step 3: Scanner Changes — `backend/app/services/scanner.py`

### 3a. New tracks → PENDING_REVIEW

In `scan()`, the two "NEW" code paths (line ~438 collision case, line ~457 normal case):
- Set `status=TrackStatus.PENDING_REVIEW` on the created track
- Do NOT append to `pending_analysis_ids` (analysis waits for approval)
- Increment new counter `results["pending_review"]` instead of `results["new"]`

### 3b. Run duplicate detection for new tracks

After creating a pending track, call `detect_duplicate_for_track()` and store result in `track.review_info`.

Performance note: duplicate detection queries the DB per-track. Since new file discovery is already I/O-bound and typically a small fraction of scanned files, this is acceptable. Could batch if needed later.

### 3c. Existing behavior unchanged

- **SKIPPED tracks**: Already in `existing_paths`, scanner sees them as "existing unchanged" → no re-flagging. Correct.
- **PENDING_REVIEW tracks on re-scan**: Same — seen as existing. If file changed, metadata re-read but status stays PENDING_REVIEW. Correct.
- **Relocated/recovered/updated tracks**: Stay ACTIVE, no review. Correct.

### 3d. Update sync progress reporting

In `backend/app/services/tasks/library_sync.py`, add `pending_review` to the progress stats so the frontend can show how many new tracks need review.

## Step 4: Fix Track Listing Status Filters

`backend/app/api/routes/tracks/listing.py` does NOT filter by status — PENDING_REVIEW tracks would appear in the main library.

Add `Track.status == TrackStatus.ACTIVE` to:
- `list_track_ids` (line ~71)
- `list_tracks` (line ~237)
- `get_track_index` (line ~408)

Leave `get_tracks_batch` unfiltered (fetches by explicit IDs, used by review queue too).

Also add `status: str` field to `TrackResponse` in `backend/app/api/routes/tracks/__init__.py` so the frontend knows each track's state.

## Step 5: Pending Review API — `backend/app/api/routes/pending_review.py` (new)

Register in `backend/app/main.py` at `/api/pending-tracks`.

### Group concept

Groups are derived server-side from each pending track's `file_path` — the immediate parent directory is the group key. The API returns tracks organized into groups. No separate "group" table is needed; grouping is computed at query time via SQL `regexp_replace` or Python path parsing.

### Endpoints

**`GET /groups`** — List import groups
- Query params: `sort_by` (folder_name, track_count, created_at), `sort_order`, `search`, `limit`, `offset`
- Returns list of groups, each containing:
  ```json
  {
    "folder_path": "/music/Artist - Album",
    "folder_name": "Artist - Album",
    "track_count": 15,
    "duplicate_count": 3,
    "upgrade_count": 2,
    "downgrade_count": 1,
    "earliest_scan": "2026-03-19T...",
    "tracks": [{ ...track with review_info... }]
  }
  ```
- `tracks` array included inline (groups are typically ≤30 tracks, and the user needs them for the expanded view)

**`GET /stats`** — Counts for sidebar badge
- Returns `{ total_tracks, total_groups, with_duplicates, upgrades, downgrades }`

**`POST /{track_id}/approve`** — Accept a single track
- Body: `{ metadata_overrides?: { artist?, album?, title?, track_number?, year? }, queue_analysis?: bool }`
- Sets status → ACTIVE, applies overrides, clears `review_info`, optionally queues analysis

**`POST /{track_id}/replace`** — Replace an existing duplicate
- Body: `{ replace_track_id: str, metadata_overrides?: {...}, queue_analysis?: bool, transfer_user_data?: bool }`
- New track → ACTIVE, old track → SKIPPED
- If `transfer_user_data`: migrate favorites, playlist entries, play history from old → new track

**`POST /{track_id}/skip`** — Permanently ignore
- Sets status → SKIPPED, clears `review_info`

**`PATCH /{track_id}/metadata`** — Edit metadata before approving
- Body: `{ artist?, album?, title?, track_number?, year? }`
- Updates track fields in-place

**`POST /group/approve`** — Approve an entire group
- Body: `{ folder_path: str, queue_analysis?: bool, metadata_overrides?: { artist?, album?, year? } }`
- Sets all PENDING_REVIEW tracks in that folder to ACTIVE
- Applies shared metadata overrides to all tracks in the group

**`POST /group/skip`** — Skip an entire group
- Body: `{ folder_path: str }`

**`POST /group/replace-upgrades`** — Replace all upgrades within a group
- Body: `{ folder_path: str, queue_analysis?: bool }`
- Finds tracks in group where `review_info.trump_status == 'trumps'`, replaces their duplicates

**`POST /group/skip-downgrades`** — Skip all downgrades within a group
- Body: `{ folder_path: str }`

**`POST /group/metadata`** — Edit shared metadata for all tracks in a group
- Body: `{ folder_path: str, metadata: { artist?, album?, year? } }`
- Applies to all PENDING_REVIEW tracks in the folder

**`POST /bulk/approve-all`** — Approve everything (global)
- Body: `{ queue_analysis?: bool }`

**`POST /bulk/skip-all`** — Skip everything (global)

### Replace flow detail

```python
# 1. New track → ACTIVE
new_track.status = TrackStatus.ACTIVE
new_track.review_info = None

# 2. Old track → SKIPPED (stays in DB so scanner won't re-discover its file)
old_track.status = TrackStatus.SKIPPED

# 3. Transfer user data (if requested)
# UPDATE profile_favorites SET track_id = new WHERE track_id = old
# UPDATE playlist_tracks SET track_id = new WHERE track_id = old
# UPDATE profile_play_history SET track_id = new WHERE track_id = old

# 4. Queue analysis if requested
```

## Step 6: Frontend API Layer — `packages/frontend/src/api/pendingTracks.ts` (new)

Types: `PendingTrack`, `PendingTrackGroup`, `PendingTrackStats`, `ApproveRequest`, etc.
API functions: `listGroups`, `getStats`, `approve`, `replace`, `skip`, `updateMetadata`, `groupApprove`, `groupSkip`, `groupReplaceUpgrades`, `groupSkipDowngrades`, `groupMetadata`, `bulkApproveAll`, `bulkSkipAll`.

Add query keys to `packages/frontend/src/api/queryKeys.ts`.
Export from `packages/frontend/src/api/index.ts`.

## Step 7: PendingReviewBrowser Component

### New directory: `packages/frontend/src/components/Library/browsers/PendingReviewBrowser/`

**`index.ts`** — Lazy load + register browser:
```typescript
registerBrowser({
  id: 'pending-review',
  name: 'Pending Review',
  // ...
}, LazyPendingReviewBrowser);
```

**`PendingReviewBrowser.tsx`** — Main component. Follow ProposedChangesBrowser pattern:
- Header with icon (Inbox), title, group count + track count
- Global action bar: "Import All" (global), "Queue Analysis" toggle
- Filter tabs: All / Has Duplicates / Clean (no duplicates)

**Group cards** — one per folder, collapsible:
- **Collapsed view** (default): folder name, track count, duplicate summary badge, group action buttons:
  - "Import All" (one-click for clean groups — no duplicates)
  - "Skip All"
  - "Replace Upgrades" / "Skip Downgrades" (shown when applicable)
  - Edit shared metadata (artist, album, year) via inline fields or popover
- **Expanded view**: shows individual tracks within the group:
  - Track metadata (title, artist, album, format, duration)
  - Duplicate info panel when applicable (existing track info, quality comparison, match type badge)
  - Per-track action buttons: Import / Replace / Skip
  - Expandable inline metadata editor (artist, album, title, track_number, year)

Register in `packages/frontend/src/components/Library/browsers/index.ts`:
```typescript
import './PendingReviewBrowser';
```

## Step 8: Sidebar Integration — `packages/frontend/src/components/Sidebar/Sidebar.tsx`

Add to `LIBRARY_ITEMS`:
```typescript
{ path: '/library/pending-review', label: 'Review', icon: Inbox }
```

Add a pending count badge. Query `pendingTracksApi.getStats()` and show `total` next to the label. Conditionally show the item or badge only when count > 0.

## Verification

1. `cd backend && uv run pytest tests/ -x -q` — all tests pass
2. `cd packages/frontend && pnpm tsc --noEmit` — no new TS errors
3. Manual test: add new audio files to library path → run sync → verify tracks appear in Pending Review browser, NOT in main library
4. Test approve/skip/replace actions → verify tracks move to correct states
5. Re-run sync → verify SKIPPED tracks are not re-flagged
6. Grep: `PENDING_REVIEW` tracks should not appear in track listing, artist, album, or discover endpoints

## Files to Create

| File | Purpose |
|------|---------|
| `backend/migrations/versions/20260319_pending_review_status.py` | Migration |
| `backend/app/services/duplicate_detection.py` | Shared duplicate detection |
| `backend/app/api/routes/pending_review.py` | API endpoints |
| `packages/frontend/src/api/pendingTracks.ts` | Frontend API client |
| `packages/frontend/src/components/Library/browsers/PendingReviewBrowser/index.ts` | Browser registration |
| `packages/frontend/src/components/Library/browsers/PendingReviewBrowser/PendingReviewBrowser.tsx` | Review queue UI |

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/db/models/base.py` | Add PENDING_REVIEW, SKIPPED to TrackStatus |
| `backend/app/db/models/tracks.py` | Add review_info column |
| `backend/app/services/scanner.py` | New tracks → PENDING_REVIEW, run duplicate detection |
| `backend/app/services/tasks/library_sync.py` | Report pending_review count in progress |
| `backend/app/api/routes/library_import/preview.py` | Import duplicate detection from shared service |
| `backend/app/api/routes/tracks/listing.py` | Add status=ACTIVE filter |
| `backend/app/api/routes/tracks/__init__.py` | Add status field to TrackResponse |
| `backend/app/main.py` | Register pending_review router |
| `packages/frontend/src/api/queryKeys.ts` | Add pending tracks keys |
| `packages/frontend/src/api/index.ts` | Export pendingTracksApi |
| `packages/frontend/src/components/Library/browsers/index.ts` | Import PendingReviewBrowser |
| `packages/frontend/src/components/Sidebar/Sidebar.tsx` | Add Review item + badge |
