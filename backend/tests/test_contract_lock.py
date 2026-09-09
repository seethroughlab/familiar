"""The contract handshake's invariants, each of which is silent when broken (ADR-0113).

`check_contract_bump.py` guards the *schema* against changing unacknowledged. These guard the
properties that no diff would flag: a lock file that has drifted from the constants it records, a
floor raise nobody justified, and the two structural decisions the endpoint rests on — that it
touches no database, and that it sits outside the token gate.

All of it reads declarations rather than starting anything, so it runs in CI with no Docker and no
Postgres, in the manner of `test_deployment_contract.py`.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.api.auth import path_requires_token
from app.api.routes import contract as contract_route
from app.config import API_CONTRACT_VERSION, MIN_CLIENT_CONTRACT

BACKEND_ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = BACKEND_ROOT / "contract.lock.json"


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text())


class TestTheLockRecordsTheConstants:
    """A lock that disagrees with `config.py` is worse than none: it reports a state nobody is in."""

    def test_the_lock_file_exists(self) -> None:
        assert LOCK_PATH.exists(), "run `make contract-lock`"

    def test_contract_version_matches(self) -> None:
        assert _lock()["contract_version"] == API_CONTRACT_VERSION

    def test_client_floor_matches(self) -> None:
        assert _lock()["min_client_contract"] == MIN_CLIENT_CONTRACT


class TestEveryFloorRaiseIsJustified:
    """ADR-0113 point 10. Raising the floor is the only change here that can refuse an app already
    installed, and nothing can verify a build is on a device — so the record is the whole control,
    and an empty record is the failure it is guarding against."""

    def test_history_is_present_and_non_empty(self) -> None:
        assert _lock()["client_floor_history"]

    def test_the_latest_entry_is_the_current_floor(self) -> None:
        assert _lock()["client_floor_history"][-1]["floor"] == MIN_CLIENT_CONTRACT

    def test_every_entry_names_something(self) -> None:
        for entry in _lock()["client_floor_history"]:
            assert entry.get("satisfied_by", "").strip(), (
                f"floor {entry.get('floor')} was recorded without naming what satisfies it"
            )

    def test_floors_never_go_backwards_unannounced(self) -> None:
        """A lowering is safe and allowed; it just has to be visible as its own entry rather than
        an edit to an existing one."""
        floors = [entry["floor"] for entry in _lock()["client_floor_history"]]
        assert floors == sorted(set(floors), key=floors.index), "duplicate floor entries"


class TestTheEndpointCannotFailForTheWrongReason:
    def test_the_handler_takes_no_dependencies(self) -> None:
        """No `DbSession`, and nothing else injectable.

        This is the reason the handshake is its own route rather than a field on
        `/api/v1/health/system`: that one takes a `DbSession`, so a Postgres outage fails it during
        dependency injection. "The database is down" and "your app is too old" must not be the same
        signal to the check that gates every other call.
        """
        parameters = inspect.signature(contract_route.get_api_contract).parameters
        assert not parameters, f"the contract handler grew dependencies: {list(parameters)}"

    def test_it_is_outside_the_token_gate(self) -> None:
        """The handshake runs before a profile or a token exists."""
        assert path_requires_token("/api/v1/contract") is False

    def test_the_response_carries_both_numbers(self) -> None:
        fields = contract_route.ContractInfo.model_fields
        assert "contract_version" in fields
        assert "min_client_contract" in fields
