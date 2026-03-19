# Zero-Touch: Remove All Library-Write Code Paths

## Context

Familiar has ~13 API code paths that write to files in the user's music library (move/rename, tag writing, in-place remux, file deletion, import/copy). We're removing all of them — not gating behind a flag, but deleting the code entirely. After this change, Familiar will never modify, move, or delete files in the music library.

**What stays:** DB-only metadata edits, artwork cache saves, transcode cache (app-owned), preview/advisory endpoints, scanning (read-only).

## Approach: Ordered by Dependency

Remove backend services first (breaking write paths at the source), then clean up routes, then frontend, then dead code.

---

## 1. Backend Services — Remove Write Capabilities

### 1a. Delete `backend/app/services/metadata/writer.py` (entire file, 935 LOC)
- Contains `write_metadata()`, `write_artwork()`, `write_lyrics()`, `remove_artwork()`, and all format-specific tag writers
- All callers will be cleaned up in subsequent steps
- Also delete `backend/tests/test_metadata_writer.py`

### 1b. `backend/app/services/bulk_editor.py`
- Remove `from app.services.metadata.writer import write_metadata` import
- In `apply_to_tracks()`: remove `write_to_files` parameter and the entire file-write block that calls `write_metadata()`
- Keep DB-only update logic and `get_common_values()`

### 1c. `backend/app/services/proposed_changes.py`
- Remove `from app.services.metadata.writer import WriteResult, write_metadata` import
- In `apply()` (line 274): delete Step 2 (ID3 tag writing, lines 323-330) and Step 3 (file reorg, lines 332-337). Keep only Step 1 (DB update)
- Delete `_apply_metadata_to_files()` method entirely (lines 366-396)
- Remove `scope_override` param from `apply()` and `apply_batch()`
- Simplify `ApplyResult`: remove `id3_written`, `id3_errors`, `files_moved`, `files_errors` fields (or hardcode defaults for API compat)

### 1d. `backend/app/services/organizer.py`
- Delete `organize_track()`, `organize_all()`, `_cleanup_empty_dirs()`
- Remove `import shutil`
- Keep: `preview_track()`, `preview_all()`, `_format_path()`, `TEMPLATES`, helpers, models

### 1e. `backend/app/services/flac_remux.py`
- Delete in-place functions: `remux_flac_in_place()`, `reencode_flac_in_place()`, `remux_audio_in_place()`, `REMUX_FORMATS`
- Keep: `detect_codec()`, `needs_transcode_check()`, `transcode_to_file()` (writes to app-owned cache), `needs_remux()`, `has_decode_errors()`

### 1f. `backend/app/services/import_service.py`
- Delete: `ImportService` class, `ImportExecuteService` class, `save_upload_to_temp()`, `convert_audio()`, `embed_artwork()`, `cleanup_expired_sessions()`
- Keep: `ImportPreviewService`, `parse_filename_metadata()`, `estimate_converted_size()`, `MusicImportError`, `CONVERTIBLE_FORMATS`

---

## 2. Backend Routes — Remove/Simplify Endpoints

### 2a. `backend/app/api/routes/organizer.py`
- Delete endpoints: `run_organization()` (POST `/run`) and `organize_track()` (POST `/track/{id}`)
- Delete request models: `OrganizeRequest`, `OrganizeTrackRequest`
- Keep: `list_templates()`, `preview_organization()`, `preview_track()`

### 2b. `backend/app/api/routes/library_deduplicate.py`
- Delete endpoint: `deduplicate_execute()` (POST `/execute`)
- Delete models: `DeduplicateExecuteRequest`, `DeduplicateExecuteResponse`
- Keep: `deduplicate_preview()` and all helpers

### 2c. `backend/app/api/routes/library_import/quick.py`
- Delete endpoints: `import_music()` (POST `/import`) and `import_from_path()` (POST `/import/from-path`)
- Delete models: `ImportResult`, `ImportFromPathRequest`
- Keep: `scan_path()` (GET `/import/scan-path`), `get_recent_imports()` (GET `/imports/recent`)

### 2d. `backend/app/api/routes/library_import/preview.py`
- Delete endpoint: `import_execute()` (POST `/import/execute`)
- Delete models: `ImportExecuteRequest`, `ImportExecuteResponse`, `ImportTrackInput`, `ImportOptions`
- Keep: `import_preview()`, `import_preview_from_path()`, duplicate detection helpers

### 2e. `backend/app/api/routes/tracks/metadata.py`
- `TrackMetadataUpdateRequest`: remove `write_to_file` field
- `TrackMetadataResponse`: remove `file_write_status` and `file_write_error` fields
- `update_track_metadata()`: delete the entire `if request.write_to_file` block (lines 268-304) including the lazy import of writer
- `BulkMetadataUpdateRequest`: remove `write_to_files` field
- `bulk_update_metadata()`: remove `write_to_files` passthrough to service
- Remove `check_library_write_allowed` and `HTTPException` imports (no longer needed)

### 2f. `backend/app/api/routes/tracks/streaming.py`
- `stream_track()`: delete the entire FLAC PTS auto-remux block (lines 85-107) — serve files as-is
- `report_playback_error()`: delete `_validate_and_fix_track()` background task call. Return `{"status": "skipped", "reason": "auto-repair removed"}`. Delete `_validate_and_fix_track()` function entirely (lines 175-238)
- `upload_track_artwork()`: remove `embed_in_file` query param and the embed block. Endpoint saves to cache only
- `delete_track_artwork()`: remove `remove_from_file` query param (already a no-op)
- Remove `check_library_write_allowed` and `HTTPException` imports

### 2g. `backend/app/api/routes/proposed_changes.py`
- `apply_change()`: remove `scope` query param. Always apply DB_ONLY
- `batch_apply()`: remove `scope` from `BatchApplyRequest`. Always apply DB_ONLY
- `CreateChangeRequest`: hardcode `scope = "db_only"` or remove field
- Remove `check_library_write_allowed` and `HTTPException` imports

---

## 3. Backend Model & Cleanup

### 3a. `backend/app/db/models/base.py`
- Remove `DB_AND_ID3` and `DB_ID3_FILES` from `ChangeScope` enum. Keep only `DB_ONLY`
- Need migration to update existing rows with old scope values → `db_only`

### 3b. Database migration — `backend/migrations/versions/YYYYMMDD_remove_file_write_scopes.py`
- `UPDATE proposed_changes SET scope = 'db_only' WHERE scope IN ('db_and_id3', 'db_id3_files')`
- Use idempotent helpers from `migrations.helpers`

### 3c. `backend/app/api/deps.py`
- Delete `require_library_write()`, `RequireLibraryWrite`, `check_library_write_allowed()` (all partially added during interrupted Phase 1 attempt)
- Remove `get_app_settings_service` import if only used by these

### 3d. `backend/app/services/app_settings.py`
- Remove `library_write_enabled` field (partially added during interrupted Phase 1 attempt)

### 3e. `backend/app/api/routes/settings.py`
- Remove `library_write_enabled` from `SettingsResponse` and `SettingsUpdateRequest` (partially added during interrupted Phase 1 attempt)

---

## 4. Frontend — Remove Write UI

### 4a. `packages/frontend/src/components/TrackEdit/TrackEditModal.tsx`
- Remove `writeToFile` state (line 62) and the "Write changes to audio file" checkbox (lines 343-350)
- Remove `write_to_file` from `updateMetadata` calls (lines 198, 225-229)
- Remove `writeToFiles` from bulk update call (line 223)

### 4b. `packages/frontend/src/components/TrackEdit/tabs/ArtworkTab.tsx`
- Remove `embedInFile` state (line 18) and "Embed in audio file tags" checkbox (lines 194-202)
- Always call artwork upload without `embed_in_file` (or with `false`)

### 4c. `packages/frontend/src/components/Settings/LibraryOrganizer.tsx`
- Remove "Organize" button and `organizeMutation` (line 40, lines 166-181)
- Remove "This will move files on disk" warning (lines 134-150)
- Keep preview button and template selector. Add note that this is preview-only

### 4d. Proposed Changes UI — two files:
- `packages/frontend/src/components/Settings/ProposedChangesPanel.tsx` — remove `db_and_id3` and `db_id3_files` from `SCOPE_LABELS`/`SCOPE_LABELS_SHORT`, remove scope dropdown selector
- `packages/frontend/src/components/Library/browsers/ProposedChangesBrowser/ProposedChangesBrowser.tsx` — same scope cleanup

### 4e. Import UI — `packages/frontend/src/components/Import/`
- Remove the entire Import Modal and GlobalDropZone (file upload no longer makes sense)
- The preview service and duplicate detection logic are kept on the backend for future inbox review feature
- Remove import triggers from AppShell and any nav entries

### 4f. `packages/frontend/src/api/metadata.ts`
- Remove `organizerApi.run()` and `organizerApi.organizeTrack()`
- Remove `ChangeScope` type entries for `db_and_id3` and `db_id3_files`
- Remove scope param from `proposedChangesApi.apply()` and `batchApply()`

### 4g. `packages/frontend/src/api/importSession.ts`
- Remove `execute()` function

### 4h. `packages/frontend/src/api/settings.ts`
- Remove `library_write_enabled` from `AppSettingsResponse` and `AppSettingsUpdate`

### 4i. `packages/frontend/src/api/tracks.ts`
- Remove `write_to_files` param from `bulkTracksApi.updateMetadata()`

---

## 5. Revert Partial Phase 1 Changes

The previous (interrupted) conversation partially applied Phase 1 guard changes. These need to be reverted since we're doing full removal instead:

- `backend/app/api/deps.py` — added `require_library_write`, `RequireLibraryWrite`, `check_library_write_allowed`, `get_app_settings_service` import
- `backend/app/services/app_settings.py` — added `library_write_enabled: bool = False`
- `backend/app/api/routes/organizer.py` — added guard imports and inline checks
- `backend/app/api/routes/library_deduplicate.py` — added `RequireLibraryWrite` dependency
- `backend/app/api/routes/library_import/quick.py` — added `RequireLibraryWrite` dependency
- `backend/app/api/routes/library_import/preview.py` — added `RequireLibraryWrite` dependency
- `backend/app/api/routes/tracks/metadata.py` — added `check_library_write_allowed` and `HTTPException` import, inline guards
- `backend/app/api/routes/tracks/streaming.py` — added `check_library_write_allowed` and `HTTPException` import, inline guards
- `backend/app/api/routes/proposed_changes.py` — added `check_library_write_allowed` and `HTTPException` import, inline guards
- `backend/app/api/routes/settings.py` — added `library_write_enabled` to response/request models

These will be cleaned up as part of the removal work (sections 2-3 above supersede them).

---

## File Summary

| File | Action |
|------|--------|
| `backend/app/services/metadata/writer.py` | **DELETE** |
| `backend/tests/test_metadata_writer.py` | **DELETE** |
| `backend/app/services/bulk_editor.py` | Remove file-write path |
| `backend/app/services/proposed_changes.py` | Remove ID3/file scopes, simplify to DB-only |
| `backend/app/services/organizer.py` | Remove execute methods |
| `backend/app/services/flac_remux.py` | Remove in-place functions |
| `backend/app/services/import_service.py` | Remove ImportService, ImportExecuteService |
| `backend/app/api/routes/organizer.py` | Remove execute endpoints |
| `backend/app/api/routes/library_deduplicate.py` | Remove execute endpoint |
| `backend/app/api/routes/library_import/quick.py` | Remove import/from-path endpoints |
| `backend/app/api/routes/library_import/preview.py` | Remove execute endpoint |
| `backend/app/api/routes/tracks/metadata.py` | Remove write_to_file params and file-write blocks |
| `backend/app/api/routes/tracks/streaming.py` | Remove FLAC remux, playback repair, embed_in_file |
| `backend/app/api/routes/proposed_changes.py` | Remove scope param, always DB_ONLY |
| `backend/app/api/routes/settings.py` | Remove library_write_enabled |
| `backend/app/db/models/base.py` | Remove DB_AND_ID3, DB_ID3_FILES from ChangeScope |
| `backend/app/api/deps.py` | Remove guard functions |
| `backend/app/services/app_settings.py` | Remove library_write_enabled |
| `backend/migrations/versions/` | New migration for scope data cleanup |
| `packages/frontend/src/components/TrackEdit/TrackEditModal.tsx` | Remove write-to-file checkbox |
| `packages/frontend/src/components/TrackEdit/tabs/ArtworkTab.tsx` | Remove embed-in-file checkbox |
| `packages/frontend/src/components/Settings/LibraryOrganizer.tsx` | Remove organize button |
| `packages/frontend/src/components/Settings/ProposedChangesPanel.tsx` | Remove file-write scopes |
| `packages/frontend/src/components/Library/browsers/ProposedChangesBrowser/` | Remove file-write scopes |
| `packages/frontend/src/components/Import/ImportModal.tsx` | Remove execute functionality |
| `packages/frontend/src/api/metadata.ts` | Remove write APIs and scope types |
| `packages/frontend/src/api/importSession.ts` | Remove execute() |
| `packages/frontend/src/api/settings.ts` | Remove library_write_enabled |
| `packages/frontend/src/api/tracks.ts` | Remove write_to_files param |

---

## Verification

1. `cd backend && uv run pytest tests/ -x -q` — no regressions (writer tests deleted, all others pass)
2. `cd packages/frontend && pnpm tsc --noEmit` — no TypeScript errors
3. Manual: `GET /api/v1/settings` — no `library_write_enabled` field
4. Manual: `POST /api/v1/library/organize/run` → 404 (endpoint removed)
5. Manual: `POST /api/v1/deduplicate/execute` → 404
6. Manual: `POST /api/v1/import` → 404
7. Manual: `PATCH /api/v1/tracks/{id}/metadata` with metadata → 200 (DB-only, no `write_to_file` param)
8. Manual: `GET /api/v1/tracks/{id}/stream` for FLAC → streams without modifying file
9. Frontend: metadata edit modal has no "write to file" checkbox
10. Frontend: artwork upload has no "embed in file" checkbox
11. Frontend: organizer shows preview only, no execute button
