"""`python -m app.token` prints the sign-in link again (ADR-0141 point 2)."""

from __future__ import annotations

import app.serve as serve
from app import token as token_command


def test_it_prints_the_link(monkeypatch, capsys):
    monkeypatch.setattr(serve, "configured_token", lambda: "abc123")
    assert token_command.main() == 0
    assert capsys.readouterr().out.strip().endswith("/#token=abc123")


def test_a_server_without_a_token_says_so(monkeypatch, capsys):
    monkeypatch.setattr(serve, "configured_token", lambda: None)
    assert token_command.main() == 1
    assert "no token" in capsys.readouterr().err
