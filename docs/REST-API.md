# Familiar API Reference

Backend API documentation for contributors. All endpoints are prefixed with `/api/v1`.

## Overview

### Base URL
```
http://localhost:4400/api/v1
```

### Authentication
Familiar uses profile-based multi-user support. Include the profile ID header:
```
X-Profile-ID: <profile-uuid>
```

Some endpoints (play history, favorites) require this header.

### Common Response Patterns
- Paginated lists return `{ items, total, page, page_size }`
- Errors return the standard envelope (see [ERROR-CONTRACTS.md](ERROR-CONTRACTS.md))

---

## Library Browsing

### List Artists

```
GET /library/artists
```

Get distinct artists with aggregated statistics.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | - | Filter by artist name |
| `sort_by` | string | `name` | Sort by: `name`, `track_count`, `album_count` |
| `page` | int | 1 | Page number |
| `page_size` | int | 100 | Items per page |

```bash
curl "http://localhost:4400/api/v1/library/artists?sort_by=track_count&page_size=10"
```

```json
{
  "items": [
    {
      "name": "Radiohead",
      "track_count": 94,
      "album_count": 9,
      "first_track_id": "a1b2c3d4-..."
    }
  ],
  "total": 156,
  "page": 1,
  "page_size": 10
}
```

### List Albums

```
GET /library/albums
```

Get distinct albums with metadata.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `artist` | string | - | Filter by artist name |
| `search` | string | - | Search album or artist name |
| `sort_by` | string | `name` | Sort by: `name`, `year`, `track_count`, `artist` |
| `page` | int | 1 | Page number |
| `page_size` | int | 100 | Items per page |

```bash
curl "http://localhost:4400/api/v1/library/albums?artist=Radiohead"
```

```json
{
  "items": [
    {
      "name": "OK Computer",
      "artist": "Radiohead",
      "year": 1997,
      "track_count": 12,
      "first_track_id": "a1b2c3d4-..."
    }
  ],
  "total": 9,
  "page": 1,
  "page_size": 100
}
```

### List Tracks

```
GET /tracks
```

Get tracks with comprehensive filtering and pagination.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | - | Search title, artist, or album |
| `artist` | string | - | Filter by artist |
| `album` | string | - | Filter by album |
| `genre` | string | - | Filter by genre |
| `year_from` | int | - | Minimum year (inclusive) |
| `year_to` | int | - | Maximum year (inclusive) |
| `energy_min` | float | - | Minimum energy (0-1) |
| `energy_max` | float | - | Maximum energy (0-1) |
| `valence_min` | float | - | Minimum valence (0-1) |
| `valence_max` | float | - | Maximum valence (0-1) |
| `include_features` | bool | false | Include audio analysis features |
| `page` | int | 1 | Page number |
| `page_size` | int | 50 | Items per page (max 200) |

```bash
curl "http://localhost:4400/api/v1/tracks?artist=Radiohead&include_features=true&page_size=5"
```

```json
{
  "items": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "file_path": "/music/Radiohead/OK Computer/01 - Airbag.flac",
      "title": "Airbag",
      "artist": "Radiohead",
      "album": "OK Computer",
      "album_artist": "Radiohead",
      "album_type": "album",
      "track_number": 1,
      "disc_number": 1,
      "year": 1997,
      "genre": "Alternative Rock",
      "duration_seconds": 284.5,
      "format": "flac",
      "analysis_version": 3,
      "features": {
        "bpm": 122.5,
        "key": "A minor",
        "energy": 0.72,
        "valence": 0.45,
        "danceability": 0.65,
        "acousticness": 0.12,
        "instrumentalness": 0.05,
        "speechiness": 0.03
      }
    }
  ],
  "total": 94,
  "page": 1,
  "page_size": 5
}
```

---

## Track Details

### Get Track

```
GET /tracks/{track_id}
```

Get a single track with its analysis features.

```bash
curl "http://localhost:4400/api/v1/tracks/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

### Stream Audio

```
GET /tracks/{track_id}/stream
```

Stream audio file with HTTP range request support for seeking.

```bash
# Full file
curl "http://localhost:4400/api/v1/tracks/{id}/stream" -o track.mp3

# Partial content (seeking)
curl -H "Range: bytes=0-65535" "http://localhost:4400/api/v1/tracks/{id}/stream"
```

Returns `206 Partial Content` with `Content-Range` header for range requests.

### Get Artwork

```
GET /tracks/{track_id}/artwork
```

Get album artwork (extracted from audio file and cached).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `size` | string | `full` | Size: `full` or `thumb` |

```bash
curl "http://localhost:4400/api/v1/tracks/{id}/artwork?size=thumb" -o cover.jpg
```

Returns JPEG image with 1-year cache header.

### Get Lyrics

```
GET /tracks/{track_id}/lyrics
```

Get lyrics for a track (synced with timestamps if available).

```bash
curl "http://localhost:4400/api/v1/tracks/{id}/lyrics"
```

```json
{
  "synced": true,
  "lines": [
    { "time": 12.5, "text": "In the next world war" },
    { "time": 15.2, "text": "In a jackknifed juggernaut" }
  ],
  "plain_text": "In the next world war\nIn a jackknifed juggernaut...",
  "source": "lrclib"
}
```

### Find Similar Tracks

```
GET /tracks/{track_id}/similar
```

Find similar tracks using CLAP embedding similarity (pgvector cosine distance).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 10 | Number of results (max 50) |

```bash
curl "http://localhost:4400/api/v1/tracks/{id}/similar?limit=5"
```

---

## Visualizations

### Year Distribution (Timeline)

```
GET /library/years
```

Get track counts by year for timeline visualization.

```bash
curl "http://localhost:4400/api/v1/library/years"
```

```json
{
  "years": [
    { "year": 1997, "track_count": 24, "album_count": 2, "artist_count": 2 },
    { "year": 1998, "track_count": 18, "album_count": 1, "artist_count": 1 }
  ],
  "total_with_year": 1250,
  "total_without_year": 45,
  "min_year": 1965,
  "max_year": 2024
}
```

### Mood Distribution (Mood Grid)

```
GET /library/mood-distribution
```

Get energy × valence distribution for heatmap visualization.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `grid_size` | int | 10 | Grid resolution (cells per axis) |

```bash
curl "http://localhost:4400/api/v1/library/mood-distribution?grid_size=10"
```

```json
{
  "cells": [
    {
      "energy_min": 0.2,
      "energy_max": 0.3,
      "valence_min": 0.5,
      "valence_max": 0.6,
      "track_count": 25,
      "sample_track_ids": ["a1b2c3d4-...", "e5f6g7h8-..."]
    }
  ],
  "grid_size": 10,
  "total_with_mood": 1180,
  "total_without_mood": 115
}
```

### Music Map

```
GET /library/map
```

Get 2D positions for artists/albums based on audio similarity using UMAP.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity_type` | string | `artists` | Entity type: `artists` or `albums` |
| `limit` | int | 200 | Max entities (max 500) |

```bash
curl "http://localhost:4400/api/v1/library/map?entity_type=artists&limit=100"
```

```json
{
  "nodes": [
    {
      "id": "radiohead",
      "name": "Radiohead",
      "x": 0.42,
      "y": 0.68,
      "track_count": 94,
      "first_track_id": "a1b2c3d4-..."
    }
  ],
  "edges": [
    { "source": "radiohead", "target": "portishead", "weight": 0.85 }
  ],
  "entity_type": "artists",
  "total_entities": 100
}
```

---

## Library Management

### Get Statistics

```
GET /library/stats
```

Get library statistics.

```bash
curl "http://localhost:4400/api/v1/library/stats"
```

```json
{
  "total_tracks": 1295,
  "total_albums": 156,
  "total_artists": 89,
  "albums": 1295,
  "compilations": 0,
  "soundtracks": 0,
  "analyzed_tracks": 1250,
  "pending_analysis": 45,
  "pending_backfill": 0,
  "pending_melodic": 0,
  "pending_mood_tags": 0
}
```

The three totals count active tracks only, and agree with `/library/albums` and `/library/artists`
— same grouping, same canonical tables. `tests/test_library_stats.py` asserts that agreement.

**`albums`, `compilations` and `soundtracks` are deprecated and should not be displayed.** Nothing
writes `Track.album_type`, so every row keeps the column default: `albums` always equals
`total_tracks` and the other two are always `0`. This example previously showed `150` compilations
and `45` soundtracks, which no instance has ever returned. They remain on the wire only because
`library` is a generated tag (ADR-0007) and removing required fields breaks the Swift client.

### Start Library Sync

```
POST /library/sync
```

Start a unified library sync (discover files → read metadata → analyze audio).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reread_unchanged` | bool | false | Re-read metadata even for unchanged files |

```bash
curl -X POST "http://localhost:4400/api/v1/library/sync"
```

```json
{
  "status": "started",
  "message": "Library sync started"
}
```

### Get Sync Status

```
GET /library/sync/status
```

Get current sync progress.

```bash
curl "http://localhost:4400/api/v1/library/sync/status"
```

```json
{
  "status": "running",
  "message": "Reading metadata...",
  "progress": {
    "phase": "reading",
    "phase_message": "Reading metadata...",
    "files_discovered": 1500,
    "files_processed": 750,
    "files_total": 1500,
    "new_tracks": 45,
    "updated_tracks": 12,
    "unchanged_tracks": 693,
    "tracks_analyzed": 0,
    "tracks_pending_analysis": 45,
    "analysis_percent": 0.0
  }
}
```

### Cancel Sync

```
POST /library/sync/cancel
```

Cancel a running library sync.

```bash
curl -X POST "http://localhost:4400/api/v1/library/sync/cancel"
```

---

## Audio Analysis

### Get Analysis Status

```
GET /library/analysis/status
```

Get audio analysis progress with stuck detection.

```bash
curl "http://localhost:4400/api/v1/library/analysis/status"
```

```json
{
  "status": "running",
  "total": 1295,
  "analyzed": 1250,
  "pending": 45,
  "failed": 0,
  "percent": 96.5,
  "current_file": "Processing 3 tracks...",
  "with_embeddings": 1200,
  "without_embeddings": 50,
  "embeddings_enabled": true,
  "embeddings_disabled_reason": null
}
```

### Start Analysis

```
POST /library/analysis/start
```

Manually trigger analysis for unanalyzed tracks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 500 | Max tracks to queue |

```bash
curl -X POST "http://localhost:4400/api/v1/library/analysis/start?limit=100"
```

```json
{
  "status": "started",
  "queued": 45,
  "message": "Queued 45 tracks for analysis"
}
```

### Cancel Analysis

```
POST /library/analysis/cancel
```

Cancel running analysis tasks.

```bash
curl -X POST "http://localhost:4400/api/v1/library/analysis/cancel"
```

---

## Import

### Simple Import

```
POST /library/import
```

Upload a zip or audio file for import.

```bash
curl -X POST "http://localhost:4400/api/v1/library/import" \
  -F "file=@album.zip"
```

```json
{
  "status": "processing",
  "message": "Imported 12 files, scanning for metadata...",
  "import_path": "/music/_imports/2024-01-15_143022",
  "files_found": 12,
  "files": ["01 - Track One.flac", "02 - Track Two.flac"]
}
```

### Preview Import

```
POST /library/import/preview
```

Extract and scan files without importing. Returns session ID for later execution.

```bash
curl -X POST "http://localhost:4400/api/v1/library/import/preview" \
  -F "file=@album.zip"
```

```json
{
  "session_id": "abc123",
  "tracks": [
    {
      "filename": "01 - Track One.flac",
      "relative_path": "Artist/Album",
      "detected_artist": "Artist Name",
      "detected_album": "Album Name",
      "detected_title": "Track One",
      "detected_track_num": 1,
      "format": "flac",
      "duration_seconds": 245.5,
      "file_size_bytes": 35000000
    }
  ],
  "total_size_bytes": 420000000,
  "estimated_sizes": { "flac": 420000000, "mp3_320": 85000000 },
  "has_convertible_formats": true
}
```

### Execute Import

```
POST /library/import/execute
```

Execute import with user options.

```bash
curl -X POST "http://localhost:4400/api/v1/library/import/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "abc123",
    "tracks": [...],
    "options": {
      "format": "original",
      "organization": "imports",
      "duplicate_handling": "rename",
      "queue_analysis": true
    }
  }'
```

### Recent Imports

```
GET /library/imports/recent
```

Get list of recent import directories.

```bash
curl "http://localhost:4400/api/v1/library/imports/recent?limit=5"
```

---

## Missing Tracks

### List Missing Tracks

```
GET /library/missing
```

Get all tracks with MISSING or PENDING_DELETION status.

```bash
curl "http://localhost:4400/api/v1/library/missing"
```

```json
{
  "tracks": [
    {
      "id": "a1b2c3d4-...",
      "title": "Track Title",
      "artist": "Artist",
      "album": "Album",
      "file_path": "/old/path/track.flac",
      "status": "missing",
      "missing_since": "2024-01-10T12:00:00",
      "days_missing": 5
    }
  ],
  "total_missing": 3,
  "total_pending_deletion": 0
}
```

### Relocate Missing Tracks

```
POST /library/missing/relocate
```

Search a folder for missing files and relocate them by filename match.

```bash
curl -X POST "http://localhost:4400/api/v1/library/missing/relocate" \
  -H "Content-Type: application/json" \
  -d '{"search_path": "/new/music/location"}'
```

```json
{
  "found": 2,
  "not_found": 1,
  "relocated_tracks": [
    {
      "id": "a1b2c3d4-...",
      "title": "Track Title",
      "old_path": "/old/path/track.flac",
      "new_path": "/new/music/location/track.flac"
    }
  ]
}
```

### Locate Single Track

```
POST /library/missing/{track_id}/locate
```

Manually set a new path for a missing track.

```bash
curl -X POST "http://localhost:4400/api/v1/library/missing/{id}/locate" \
  -H "Content-Type: application/json" \
  -d '{"new_path": "/new/path/to/track.flac"}'
```

### Delete Missing Track

```
DELETE /library/missing/{track_id}
```

Permanently delete a missing track from the database.

```bash
curl -X DELETE "http://localhost:4400/api/v1/library/missing/{id}"
```

### Batch Delete Missing Tracks

```
DELETE /library/missing/batch
```

Delete multiple missing tracks.

```bash
curl -X DELETE "http://localhost:4400/api/v1/library/missing/batch" \
  -H "Content-Type: application/json" \
  -d '{"track_ids": ["id1", "id2", "id3"]}'
```

---

## Play History

*Requires `X-Profile-ID` header.*

### Record Play

```
POST /tracks/{track_id}/played
```

Record that a track was played.

```bash
curl -X POST "http://localhost:4400/api/v1/tracks/{id}/played" \
  -H "X-Profile-ID: your-profile-id" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 245.5}'
```

```json
{
  "track_id": "a1b2c3d4-...",
  "play_count": 15,
  "total_play_seconds": 3682.5
}
```

### Get Play Statistics

```
GET /tracks/stats/plays
```

Get play statistics for the current profile.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 10 | Number of top tracks (max 50) |

```bash
curl "http://localhost:4400/api/v1/tracks/stats/plays?limit=5" \
  -H "X-Profile-ID: your-profile-id"
```

```json
{
  "total_plays": 1250,
  "total_play_seconds": 312500.0,
  "unique_tracks": 450,
  "top_tracks": [
    {
      "id": "a1b2c3d4-...",
      "title": "Airbag",
      "artist": "Radiohead",
      "play_count": 42,
      "total_play_seconds": 11949.0,
      "last_played_at": "2024-01-15T18:30:00"
    }
  ]
}
```
