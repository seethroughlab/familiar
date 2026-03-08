# Familiar Backend

FastAPI backend for the Familiar music player.

## Development

```bash
# Install dependencies
make dev

# Apply migrations
make migrate

# Run API server (background tasks run in-process)
make run

# Reset database
make reset-db

# Run API contract/error-shape audit tests (runs migrations first)
make test-contract
```
