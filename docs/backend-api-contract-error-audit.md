# Backend API Contract + Error-Shape Audit

Generated: 2026-03-08  
Scope: player-critical endpoint groups (`tracks/stream`, `artwork`, `playlists`, `settings`)

## Contract Baseline

- Error responses are JSON objects with top-level `detail`.
- Application errors (`400/401/404`) return string `detail`.
- Validation errors (`422`) are currently normalized to string `detail` by global exception handling.

## Automated Checks Added

- Test suite: [test_api_contract_error_shapes.py](/Users/jeff/Developer/familiar/backend/tests/test_api_contract_error_shapes.py)
- Cases covered:
  - `GET /api/v1/tracks/{track_id}/stream` invalid UUID -> `422` + string `detail`
  - `GET /api/v1/artwork/{album_hash}/{size}` invalid size -> `400` + string `detail`
  - `GET /api/v1/playlists` missing profile header -> `401` + string `detail`
  - `GET /api/v1/playlists` invalid profile header format -> `400` + string `detail`
  - `PUT /api/v1/settings` invalid body type -> `422` + string `detail`

## Audit Findings

1. High: Schema drift can mask expected API-level errors.
   - During initial audit run, `GET /tracks/{uuid}/stream` returned `500` due missing DB column `tracks.full_file_hash`, before route-level 404 handling could execute.
   - Impact: contract instability in environments where migrations lag model changes.
   - Recommendation: add migration preflight checks in CI/startup and require `alembic upgrade head` before backend contract test runs.

## Validation Command

```bash
cd backend
uv run pytest tests/test_api_contract_error_shapes.py -q --no-cov
```

