"""`python -m app.token` prints the sign-in link again (ADR-0141 point 2)."""

from __future__ import annotations

import app.serve as serve
from app import token as token_command


def test_it_prints_the_link(monkeypatch, capsys):
    monkeypatch.setattr(serve, "configured_token", lambda: "abc123")
    assert token_command.main([]) == 0
    assert capsys.readouterr().out.strip().endswith("/#token=abc123")


def test_a_server_without_a_token_says_so(monkeypatch, capsys):
    monkeypatch.setattr(serve, "configured_token", lambda: None)
    assert token_command.main([]) == 1
    assert "no token" in capsys.readouterr().err


def test_create_makes_a_token_when_there_is_none(monkeypatch, capsys):
    """ADR-0171 point 4: the recovery path for a tokenless server that answers only itself."""
    monkeypatch.setattr(serve, "configured_token", lambda: None)
    monkeypatch.setattr(serve, "mint_token", lambda: "fresh")
    assert token_command.main(["--create"]) == 0
    assert capsys.readouterr().out.strip().endswith("/#token=fresh")


def test_create_never_replaces_an_existing_token(monkeypatch, capsys):
    """Rotating signs every client out; that is Server → Access's to do, not a recovery command's."""
    monkeypatch.setattr(serve, "configured_token", lambda: "kept")

    def mint():
        raise AssertionError("minted over an existing token")

    monkeypatch.setattr(serve, "mint_token", mint)
    assert token_command.main(["--create"]) == 0
    assert capsys.readouterr().out.strip().endswith("/#token=kept")
