"""The API contract version — the one endpoint a client calls before it trusts anything else.

**Why this is not part of `/health`.** `GET /api/v1/health` is a container liveness probe and
`main.py` says it stays that shape forever; `GET /api/v1/health/system` takes a `DbSession`, so a
Postgres outage fails it during dependency injection, before the handler body ever runs. That would
make "the database is down" and "your app is too old for this server" indistinguishable to the one
check that gates every other call. This handler touches nothing that can fail independently of the
process being up at all.

The numbers are source-level constants (`app.config`), deliberately not `get_app_version()`. That
reads `/app/VERSION`, which is a git tag on a `release.yml` build, the literal string `"demo"` on
every fly deploy regardless of commit, and absent entirely on a `scripts/deploy-dev.sh` rsync to the
NAS. A constant is correct on all three channels; the version string is correct on one.

ADR-0113.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import API_CONTRACT_VERSION, MIN_CLIENT_CONTRACT, get_app_version

router = APIRouter(prefix="/contract", tags=["system"])


class ContractInfo(BaseModel):
    """What a client needs to decide whether it can talk to this server."""

    contract_version: int
    min_client_contract: int
    #: Informational only — never compare against this. See the module docstring.
    server_version: str


@router.get("", response_model=ContractInfo)
async def get_api_contract() -> ContractInfo:
    """Report the API contract this server implements, and the oldest client it serves."""
    return ContractInfo(
        contract_version=API_CONTRACT_VERSION,
        min_client_contract=MIN_CLIENT_CONTRACT,
        server_version=get_app_version(),
    )
