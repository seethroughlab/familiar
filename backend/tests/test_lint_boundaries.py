"""`scripts/lint_boundaries.py` catches what it says it catches (ADR-0130 point 9)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lint_boundaries.py"
spec = importlib.util.spec_from_file_location("lint_boundaries", SCRIPT)
assert spec and spec.loader
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def test_an_operation_may_not_import_fastapi_even_inside_a_function():
    src = "def f():\n    from fastapi import Depends\n    return Depends\n"
    assert lint.check(src, "app/operations/x.py") == [
        "app/operations/x.py:2: imports fastapi — operations and the container are HTTP-free"
    ]


def test_the_container_is_held_to_the_same_rule():
    assert lint.check("from app.api.deps import get_db\n", "app/container.py")


def test_a_service_may_not_call_routes():
    src = "from app.api.routes.playlists.crud import list_playlists\n"
    assert lint.check(src, "app/services/y.py") == [
        "app/services/y.py:1: imports app.api.routes.playlists.crud — a service does not reach into routes"
    ]


def test_a_service_may_import_api_exceptions():
    """`app.api.exceptions` is the error vocabulary, not a route; that boundary is not drawn here."""
    assert lint.check("from app.api.exceptions import NotFoundError\n", "app/services/y.py") == []


def test_nothing_imports_the_assembled_app():
    assert lint.check("import app.main\n", "app/api/routes/z.py")
    assert lint.check("from app.main import app\n", "app/services/z.py")


def test_a_route_importing_an_operation_is_the_intended_direction():
    assert lint.check("from app.operations.soulseek import ProbeSoulseekStatus\n", "app/api/routes/s.py") == []


def test_the_repository_passes():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
