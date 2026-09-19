#!/usr/bin/env bash
# `make doctor` — what this machine can and cannot do with this checkout (ADR-0127 point 4).
#
# Read-only. Every check here either inspects the working tree or asks a service a question that
# changes nothing: no migration runs, no sync starts, no file is written outside /tmp. Pass an
# environment (`DATABASE_URL`, `REDIS_URL`, `TEST_DATABASE_URL`) to check it; with none set, the
# database and Redis rows report the defaults in `backend/app/config.py`.
#
# Exit status is the number of failed rows, capped at 1, so a script can gate on it. Warnings do
# not fail.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

fail=0
ok()   { printf '  \033[32m✓\033[0m %-26s %s\n' "$1" "$2"; }
warn() { printf '  \033[33m!\033[0m %-26s %s\n' "$1" "$2"; }
bad()  { printf '  \033[31m✗\033[0m %-26s %s\n' "$1" "$2"; fail=1; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "Runtimes"
for tool in python3 uv node pnpm docker ffmpeg; do
  if have "$tool"; then
    case "$tool" in
      python3) v=$(python3 --version 2>&1 | awk '{print $2}') ;;
      uv)      v=$(uv --version 2>&1 | awk '{print $2}') ;;
      node)    v=$(node --version) ;;
      pnpm)    v=$(pnpm --version) ;;
      docker)  v=$(docker --version 2>/dev/null | sed -E 's/Docker version ([^,]+),.*/\1/') ;;
      ffmpeg)  v=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}') ;;
    esac
    ok "$tool" "$v"
  else
    case "$tool" in
      docker|ffmpeg) warn "$tool" "not on PATH (docker: test-services and the image; ffmpeg: transcode tests)" ;;
      *) bad "$tool" "not on PATH" ;;
    esac
  fi
done
if [ -f backend/.python-version ]; then
  want=$(cat backend/.python-version)
  got=$(python3 --version 2>&1 | awk '{print $2}')
  case "$got" in "$want"*) ok "python pin" "$want (backend/.python-version)";; *) warn "python pin" "backend/.python-version wants $want; python3 on PATH is $got — uv will pick its own";; esac
fi

echo "Checkout"
if [ -d backend/.venv ]; then ok "backend/.venv" "present"; else warn "backend/.venv" "missing — cd backend && uv sync --extra dev"; fi
if [ -d node_modules ] && [ -e packages/frontend/node_modules/@familiar/api-client ]; then
  ok "node_modules" "present, workspace packages linked"
elif [ -d node_modules ]; then
  bad "node_modules" "present but @familiar/api-client is not linked — run pnpm install (the trap that broke the Docker build and a deploy)"
else
  warn "node_modules" "missing — pnpm install"
fi
gitdir=$(git rev-parse --git-dir 2>/dev/null || echo "")
case "$gitdir" in
  .git) warn "worktree" "this is the shared main checkout; several sessions use it — work in a worktree";;
  "")   warn "worktree" "not a git checkout";;
  *)    ok "worktree" "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)";;
esac

echo "Services"
db_url="${DATABASE_URL:-postgresql+asyncpg://familiar:familiar@localhost:5432/familiar}"
db_src=$([ -n "${DATABASE_URL:-}" ] && echo "DATABASE_URL" || echo "default")
db_name=$(printf '%s' "$db_url" | sed -E 's#^[a-z+]+://[^/]+/([^?]+).*#\1#')
db_hostport=$(printf '%s' "$db_url" | sed -E 's#^[a-z+]+://([^@/]*@)?([^/?]+).*#\2#')
db_host=${db_hostport%%:*}; db_port=${db_hostport##*:}; [ "$db_port" = "$db_host" ] && db_port=5432
if have nc && nc -z -w 2 "$db_host" "$db_port" 2>/dev/null; then
  ok "postgres" "$db_host:$db_port reachable ($db_src) · database '$db_name'"
else
  warn "postgres" "$db_host:$db_port not reachable ($db_src) — docker compose -f docker/docker-compose.yml up -d, or point DATABASE_URL elsewhere"
fi
case "$db_name" in
  *_test) ok "database identity" "'$db_name' is disposable (a _test name; the test suite would accept it)";;
  *)      ok "database identity" "'$db_name' is a real database; tests refuse it and take TEST_DATABASE_URL (ADR-0128)";;
esac
if [ -n "${TEST_DATABASE_URL:-}" ]; then
  tname=$(printf '%s' "$TEST_DATABASE_URL" | sed -E 's#^[a-z+]+://[^/]+/([^?]+).*#\1#')
  case "$tname" in *_test) ok "TEST_DATABASE_URL" "'$tname'";; *) bad "TEST_DATABASE_URL" "'$tname' does not end in _test — pytest will refuse it";; esac
else
  warn "TEST_DATABASE_URL" "unset — make test sets it; bare pytest stops before collection"
fi
redis_url="${REDIS_URL:-redis://localhost:6379/0}"
r_hostport=$(printf '%s' "$redis_url" | sed -E 's#^redis://([^@/]*@)?([^/?]+).*#\2#')
r_host=${r_hostport%%:*}; r_port=${r_hostport##*:}; [ "$r_port" = "$r_host" ] && r_port=6379
if have nc && nc -z -w 2 "$r_host" "$r_port" 2>/dev/null; then ok "redis" "$r_host:$r_port reachable"; else warn "redis" "$r_host:$r_port not reachable"; fi

echo "Migrations"
if [ -d backend/.venv ] && have nc && nc -z -w 2 "$db_host" "$db_port" 2>/dev/null; then
  out=$(cd backend && DATABASE_URL="$db_url" uv run --quiet python -c "
from app.db.migration_preflight import check_database_at_head
ok, cur, heads, why = check_database_at_head()
print('OK' if ok else 'BEHIND', ','.join(cur) or '-', ','.join(heads) or '-', why or '')
" 2>/dev/null | tail -1)
  case "$out" in
    OK*)     ok "alembic" "at head ($(echo "$out" | awk '{print $2}'))";;
    BEHIND*) warn "alembic" "database is not at head — $(echo "$out" | cut -d' ' -f4-) (cd backend && make migrate)";;
    *)       warn "alembic" "could not read migration state";;
  esac
else
  warn "alembic" "skipped (needs backend/.venv and a reachable database)"
fi

echo "Contracts"
if [ -d backend/.venv ]; then
  if (cd backend && DATABASE_URL="$db_url" uv run --quiet python scripts/dump_openapi.py --check >/dev/null 2>&1); then
    ok "openapi.json" "matches the app"
  else
    bad "openapi.json" "stale — cd backend && make openapi && make contract-lock"
  fi
  if (cd backend && DATABASE_URL="$db_url" uv run --quiet python scripts/check_contract_bump.py --check >/dev/null 2>&1); then
    ok "contract.lock.json" "locked"
  else
    bad "contract.lock.json" "the API shape moved — cd backend && make contract-lock (or bump API_CONTRACT_VERSION first)"
  fi
else
  warn "openapi.json" "skipped (needs backend/.venv)"
fi
if [ -d node_modules ]; then
  tmp=$(mktemp -d)
  if (cd packages/api-client && pnpm exec openapi-ts -i ../../backend/openapi.json -o "$tmp/generated" >/dev/null 2>&1) && diff -rq "$tmp/generated" packages/api-client/src/generated >/dev/null 2>&1; then
    ok "api-client" "generated client matches openapi.json"
  else
    bad "api-client" "generated client is stale — pnpm generate:api"
  fi
  rm -rf "$tmp"
fi

echo
if [ "$fail" = 0 ]; then echo "No failures. Warnings above are things this machine cannot do right now, not defects."; else echo "Fix the ✗ rows above."; fi
exit $fail
