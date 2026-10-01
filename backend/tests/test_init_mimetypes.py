"""The server's first static file answered 500 inside the App Sandbox.

`mimetypes` reads system tables such as /etc/apache2/mime.types on first use, the sandbox refuses
the read, and `mimetypes.init` does not catch the `PermissionError`. A table this process may not
open stands in for the sandbox here.
"""

from __future__ import annotations

import mimetypes

import pytest

from app.process_setup import init_mimetypes


@pytest.fixture
def tables(tmp_path, monkeypatch):
    forbidden = tmp_path / "forbidden.types"
    forbidden.write_text("application/x-familiar-test familiartest\n")
    forbidden.chmod(0)
    allowed = tmp_path / "allowed.types"
    allowed.write_text("application/x-familiar-allowed famallowed\n")
    monkeypatch.setattr(mimetypes, "knownfiles", [str(forbidden), str(allowed)])
    # As the server meets it: never initialised. Initialised, `init(files=…)` takes another branch,
    # and that branch is how the first version of this fix passed here and failed in the sandbox.
    monkeypatch.setattr(mimetypes, "_db", None)
    monkeypatch.setattr(mimetypes, "inited", False)
    yield forbidden, allowed
    forbidden.chmod(0o600)
    monkeypatch.undo()
    mimetypes.init()  # put the real tables back for the rest of the session


def test_the_unguarded_init_is_the_bug(tables):
    forbidden, _ = tables
    with pytest.raises(PermissionError):
        mimetypes.init(files=[str(forbidden)])


def test_only_readable_tables_are_loaded(tables):
    forbidden, allowed = tables
    assert init_mimetypes() == [str(allowed)]
    assert mimetypes.guess_type("index.html")[0] == "text/html", "Python's own table still answers"
    assert mimetypes.guess_type("x.famallowed")[0] == "application/x-familiar-allowed"
