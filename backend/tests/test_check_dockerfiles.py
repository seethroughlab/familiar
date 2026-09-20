"""`scripts/check_dockerfiles.py` catches the missing COPY that broke the demo deploy."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_dockerfiles.py"
spec = importlib.util.spec_from_file_location("check_dockerfiles", SCRIPT)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def package(name: str, deps: dict[str, str] | None = None) -> None:
        d = tmp_path / "packages" / name.split("/")[-1]
        d.mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"name": name, "dependencies": deps or {}}))

    package("@familiar/api-client")
    package("@familiar/frontend", {"@familiar/api-client": "workspace:*"})
    package("@familiar/web", {"@familiar/frontend": "workspace:*"})
    # A workspace member the web build does not reach; must not be required.
    package("@familiar/visualizer-sdk")
    monkeypatch.setattr(check, "ROOT", tmp_path)
    return tmp_path


COMPLETE = """FROM node AS frontend-builder
COPY packages/api-client/package.json packages/api-client/
COPY packages/frontend/package.json packages/frontend/
COPY packages/web/package.json packages/web/
RUN pnpm install
COPY packages/api-client/ packages/api-client/
COPY packages/frontend/ packages/frontend/
COPY packages/web/ packages/web/
RUN pnpm build
"""


def problems(repo: Path, dockerfile: str) -> list[str]:
    path = repo / "Dockerfile"
    path.write_text(dockerfile)
    required = check.reachable_from(repo / "packages" / "web", check.workspace_packages())
    return check.missing_from(path, required)


def test_reachability_is_transitive_and_stops_at_what_web_needs(repo: Path) -> None:
    required = check.reachable_from(repo / "packages" / "web", check.workspace_packages())
    assert [p.name for p in required] == ["api-client", "frontend", "web"]


def test_a_complete_dockerfile_passes(repo: Path) -> None:
    assert problems(repo, COMPLETE) == []


def test_the_missing_api_client_is_named_in_both_layers(repo: Path) -> None:
    # The shape that broke `deploy/fly/Dockerfile`: the package exists, nothing copies it.
    broken = COMPLETE.replace("COPY packages/api-client/package.json packages/api-client/\n", "").replace(
        "COPY packages/api-client/ packages/api-client/\n", ""
    )
    found = problems(repo, broken)
    assert len(found) == 2
    assert all("packages/api-client" in f for f in found)


def test_the_manifest_layer_alone_is_not_enough(repo: Path) -> None:
    broken = COMPLETE.replace("COPY packages/api-client/ packages/api-client/\n", "")
    assert problems(repo, broken) == ["packages/api-client/ is not copied before the build"]
