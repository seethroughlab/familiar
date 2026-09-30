"""`scripts/check_docs.py` catches what it says it catches (ADR-0127 point 9)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_docs.py"
spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
assert spec and spec.loader
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "main.py").write_text("")
    (tmp_path / "Makefile").write_text("help:\n\techo\n\ndev:\n\techo\n")
    (tmp_path / "package.json").write_text('{"scripts": {"build": "x", "generate:api": "y"}}')
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    return tmp_path


def run(repo: Path, text: str) -> list[str]:
    doc = repo / "DOC.md"
    doc.write_text(text)
    return check_docs.check(doc, check_docs.make_targets(), check_docs.pnpm_scripts())


def test_a_missing_path_is_reported(repo: Path) -> None:
    assert run(repo, "Edit `backend/app/nope.py`.") == ["DOC.md:1: `backend/app/nope.py` does not exist"]


def test_an_abbreviated_backend_path_resolves(repo: Path) -> None:
    assert run(repo, "See `app/main.py` and `main.py`.") == []


def test_a_line_number_and_a_placeholder_are_stripped(repo: Path) -> None:
    # `{id}` is unknowable; the path up to it is what must exist.
    assert run(repo, "See `backend/app/main.py:42` and `backend/app/{id}`.") == []
    assert run(repo, "See `backend/gone/{id}`.") == ["DOC.md:1: `backend/gone/{id}` does not exist"]


def test_commands_are_checked_only_where_the_reader_types_them(repo: Path) -> None:
    assert run(repo, "Run `make dev` and `pnpm generate:api`.") == []
    assert run(repo, "Run `make teleport` and `pnpm fly`.") == [
        "DOC.md:1: `make teleport` is not a target",
        "DOC.md:1: `pnpm fly` is not a script",
    ]
    # Prose is not a command.
    assert run(repo, "The pnpm workspace is where make targets live.") == []
    # A bash fence is.
    assert run(repo, "```bash\nmake teleport\n```") == ["DOC.md:2: `make teleport` is not a target"]


def test_output_fences_are_skipped_and_ignores_honoured(repo: Path) -> None:
    assert run(repo, "```text\nsrc/gone.py: error\n```") == []
    assert run(repo, "<!-- check-docs: ignore -->\nThere is no `backend/app/gone.py` any more.") == []


def test_not_paths(repo: Path) -> None:
    assert run(repo, "`@familiar/frontend`, `../familiar-apple`, `<Artist>/<Album>`, `YYYYMMDD_slug.py`, `/api/v1/tracks`") == []


def test_the_repository_passes() -> None:
    assert check_docs.main() == 0
