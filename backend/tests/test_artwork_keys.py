"""ADR-0176 Phase 1: artwork cannot be found by a key anyone can compute.

Artwork is readable without the server token (ADR-0045), so before this a caller could compute
`compute_album_hash(artist, album)` for a guessed album and ask `/artwork/<hash>/thumb` or
`/artwork/status/<hash>` whether the library had it. Now a hash key leaves the server only with this
server's MAC, and only that form (or an album UUID) is answered.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.services import artwork_keys
from app.services.artwork import compute_album_hash

ALBUM_HASH = compute_album_hash("Cranes", "Loved")


class _Settings:
    def __init__(self):
        self.state = {"artwork_key_secret": None, "access_token": None}

    def get(self):
        return type("S", (), dict(self.state))()

    def update(self, **kw):
        self.state.update(kw)


@pytest.fixture
def settings(monkeypatch):
    fake = _Settings()
    monkeypatch.setattr("app.services.app_settings.get_app_settings_service", lambda: fake)
    return fake


# ── The key ─────────────────────────────────────────────────────────────────────────────────────


def test_an_issued_hash_key_is_accepted_and_a_bare_one_is_not(settings):
    issued = artwork_keys.issue(ALBUM_HASH)
    assert issued.startswith(ALBUM_HASH + ".") and issued != ALBUM_HASH
    assert artwork_keys.accept(issued) == ALBUM_HASH
    assert artwork_keys.accept(ALBUM_HASH) is None


def test_an_album_uuid_passes_unchanged(settings):
    album_id = str(uuid4())
    assert artwork_keys.issue(album_id) == album_id
    assert artwork_keys.accept(album_id) == album_id


@pytest.mark.parametrize(
    "key",
    [
        "0123456789abcdef.0000000000000000",  # right shape, wrong MAC
        "../../settings",
        "..",
        "0123456789abcdef.",
        "",
        "not-a-key",
    ],
)
def test_anything_else_is_refused(settings, key):
    assert artwork_keys.accept(key) is None


def test_a_mac_from_another_server_is_refused(settings):
    issued = artwork_keys.issue(ALBUM_HASH)
    settings.state["artwork_key_secret"] = None  # another server: a different secret is minted
    assert artwork_keys.accept(issued) is None


def test_the_secret_is_minted_once_and_kept(settings):
    first = artwork_keys.issue(ALBUM_HASH)
    secret = settings.state["artwork_key_secret"]
    assert secret and len(secret) == 64
    assert artwork_keys.issue(ALBUM_HASH) == first
    assert settings.state["artwork_key_secret"] == secret


def test_the_secret_never_leaves_in_the_settings_view(tmp_path):
    from app.services.app_settings import AppSettingsService

    service = AppSettingsService(settings_path=tmp_path / "settings.json")
    service.update(artwork_key_secret="ab" * 32)
    assert "artwork_key_secret" not in service.get_masked()


# ── The routes ──────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def art(tmp_path, monkeypatch):
    """One album's artwork on disk, filed under its derivable hash."""
    (tmp_path / f"{ALBUM_HASH}.jpg").write_bytes(b"\xff\xd8full")
    (tmp_path / f"{ALBUM_HASH}_thumb.jpg").write_bytes(b"\xff\xd8thumb")

    def path(key, size="full"):
        return tmp_path / (f"{key}.jpg" if size == "full" else f"{key}_{size}.jpg")

    monkeypatch.setattr("app.api.routes.artwork.get_artwork_path", path)
    monkeypatch.setattr("app.services.artwork.is_generated_artwork", lambda key: False)
    return tmp_path


async def _client():
    from app.main import app

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def test_the_image_answers_an_issued_key_and_not_a_derived_one(settings, art):
    async with await _client() as client:
        derived = await client.get(f"/api/v1/artwork/{ALBUM_HASH}/thumb")
        issued = await client.get(f"/api/v1/artwork/{artwork_keys.issue(ALBUM_HASH)}/thumb")
    assert derived.status_code == 404, "a derived hash must not reveal that the album exists"
    assert issued.status_code == 200 and issued.content == b"\xff\xd8thumb"


async def test_the_status_route_answers_an_issued_key_and_not_a_derived_one(settings, art):
    async with await _client() as client:
        derived = await client.get(f"/api/v1/artwork/status/{ALBUM_HASH}")
        key = artwork_keys.issue(ALBUM_HASH)
        issued = await client.get(f"/api/v1/artwork/status/{key}")
    assert derived.status_code == 404
    assert issued.status_code == 200
    assert issued.json()["exists"] is True and issued.json()["album_hash"] == key


async def test_the_queue_hands_out_issued_keys(settings, art, monkeypatch):
    """What a client receives is what it must send back; a bare hash would now be refused."""
    from app.api.deps import get_db
    from app.main import app

    async def key_for_tags(db, artist, album):
        return ALBUM_HASH

    async def no_db():
        yield None

    monkeypatch.setattr("app.api.routes.artwork.album_key_for_tags", key_for_tags)
    monkeypatch.setattr("app.api.routes.artwork.should_refetch_online", lambda key: False)
    app.dependency_overrides[get_db] = no_db
    try:
        async with await _client() as client:
            single = await client.post("/api/v1/artwork/queue", json={"artist": "Cranes", "album": "Loved"})
            batch = await client.post(
                "/api/v1/artwork/queue/batch", json={"items": [{"artist": "Cranes", "album": "Loved"}]}
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
    issued = artwork_keys.issue(ALBUM_HASH)
    assert single.json()["album_hash"] == issued
    assert batch.json()["results"][0]["album_key"] == issued
    assert batch.json()["existing_hashes"] == [issued]
