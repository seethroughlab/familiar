"""The backup nobody has ever restored from.

`s3_backup.py` is 1,156 lines that run on a scheduler and write a whole Familiar
installation to S3 — pg_dump and settings to Standard, audio and artwork to
Glacier Deep Archive, content-addressed by hash, with a manifest that makes the
next run incremental. Until this file it had **no test of any kind**, and its
restore path had no caller either, so the only operation that matters in an
emergency had never been executed.

These use `moto`, which implements S3 in-process. The parts genuinely outside
Python — `pg_dump` and `psql` — are stubbed, and asserted on separately; the
storage logic underneath is exercised for real.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

from app.services import s3_backup as s3mod  # noqa: E402

BUCKET = "familiar-backup-test"
REGION = "us-east-1"


def _write_tracks(url: str, rows: list[dict]) -> None:
    """(Re)create the `tracks` table the audio phase queries."""
    import sqlalchemy

    engine = sqlalchemy.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("DROP TABLE IF EXISTS tracks"))
        conn.execute(
            sqlalchemy.text(
                "CREATE TABLE tracks (id TEXT, file_path TEXT, file_hash TEXT, file_size INTEGER)"
            )
        )
        for t in rows:
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO tracks VALUES (:id, :file_path, :file_hash, :file_size)"
                ),
                t,
            )
    engine.dispose()


class FakeRedis:
    """The subset s3_backup uses: set/get/delete/expire/lpush/lrange/ltrim."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def get(self, key):
        return self.kv.get(key)

    def delete(self, *keys):
        for k in keys:
            self.kv.pop(k, None)
            self.lists.pop(k, None)
        return True

    def expire(self, key, seconds):
        return True

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        self.lists[key] = items[start:] if end == -1 else items[start : end + 1]
        return True


@pytest.fixture
def fake_redis():
    r = FakeRedis()
    with patch.object(s3mod, "get_resilient_redis", return_value=r):
        yield r


@pytest.fixture
def s3_settings():
    """Credentials that moto accepts, with backup enabled."""
    cfg = SimpleNamespace(
        s3_backup_enabled=True,
        s3_backup_schedule="weekly",
    )
    effective = {
        "s3_backup_bucket": BUCKET,
        "s3_backup_region": REGION,
        "s3_backup_access_key_id": "testing",
        "s3_backup_secret_access_key": "testing",
        "s3_backup_prefix": "",
    }
    svc = SimpleNamespace(
        get=lambda: cfg,
        get_effective=lambda k: effective.get(k),
        has_s3_credentials=lambda: True,
    )
    with patch.object(s3mod, "get_app_settings_service", return_value=svc):
        yield effective


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Two real audio files on disk, and a `tracks` table that names them.

    Points `sync_database_url` at a SQLite file rather than patching
    `create_engine`, which `s3_backup` imports inside the function — so the real
    query runs against a real engine.
    """
    audio_dir = tmp_path / "music"
    audio_dir.mkdir()
    tracks = []
    for i, content in enumerate([b"RIFF-one-" + b"a" * 400, b"RIFF-two-" + b"b" * 900]):
        p = audio_dir / f"track{i}.flac"
        p.write_bytes(content)
        tracks.append(
            {
                "id": f"0000000{i}-0000-0000-0000-00000000000{i}",
                "file_path": str(p),
                "file_hash": hashlib.sha256(content).hexdigest(),
                "file_size": len(content),
            }
        )

    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"library_paths": [str(audio_dir)]}))

    db_path = tmp_path / "library.db"
    url = f"sqlite:///{db_path}"
    _write_tracks(url, tracks)
    # `sync_database_url` is a read-only property, so patch it on the class.
    monkeypatch.setattr(
        type(s3mod.app_config),
        "sync_database_url",
        property(lambda self: url),
        raising=False,
    )

    yield SimpleNamespace(tracks=tracks, audio_dir=audio_dir, root=tmp_path, db_url=url)


@pytest.fixture
def fake_pg(tmp_path):
    """pg_dump/psql are the only things genuinely outside Python. Stub them."""
    dump_payload = b"-- fake pg_dump\nCREATE TABLE tracks();\n"

    def fake_dump(self, client, bucket, prefix):
        key = s3mod._s3_key(prefix, "database/dump.sql.gz")
        body = gzip.compress(dump_payload)
        client.put_object(Bucket=bucket, Key=key, Body=body)
        return key, len(body), "sha256:" + hashlib.sha256(body).hexdigest()

    restored: dict = {}

    def fake_restore(self, client, bucket, s3_key):
        obj = client.get_object(Bucket=bucket, Key=s3_key)
        restored["bytes"] = gzip.decompress(obj["Body"].read())

    def fake_pg_dump_to(self, out_path):
        Path(out_path).write_bytes(gzip.compress(dump_payload))

    with (
        patch.object(s3mod.S3BackupService, "_backup_database", fake_dump),
        patch.object(s3mod.S3BackupService, "_restore_database", fake_restore),
        patch.object(s3mod.S3BackupService, "_pg_dump_to", fake_pg_dump_to),
    ):
        yield SimpleNamespace(payload=dump_payload, restored=restored)


def _service():
    return s3mod.S3BackupService()


def _bucket(client):
    client.create_bucket(Bucket=BUCKET)


# --- backup -----------------------------------------------------------------


@mock_aws
def test_backup_stores_audio_content_addressed_by_hash(fake_redis, s3_settings, library, fake_pg):
    """The key is the hash, not the path — that is what makes it deduplicating."""
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)

    result = _service().run_backup()
    assert result.get("status") != "error", result

    keys = {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])}
    for t in library.tracks:
        h = t["file_hash"]
        assert f"audio/{h[:4]}/{h}.flac" in keys, f"missing {h[:4]}/{h}"


@mock_aws
def test_audio_goes_to_deep_archive_and_the_manifest_stays_instantly_readable(
    fake_redis, s3_settings, library, fake_pg
):
    """The cost model in `estimate_cost` depends on exactly this split.

    Audio in Deep Archive is ~$0.00099/GB/month; the manifest has to be readable
    without a 12-hour thaw or an incremental backup could never start.
    """
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()

    h = library.tracks[0]["file_hash"]
    audio = client.head_object(Bucket=BUCKET, Key=f"audio/{h[:4]}/{h}.flac")
    assert audio.get("StorageClass") == "DEEP_ARCHIVE"

    manifest = client.head_object(Bucket=BUCKET, Key="manifest.json")
    assert manifest.get("StorageClass") in (None, "STANDARD")


@mock_aws
def test_a_second_backup_skips_files_whose_hash_has_not_changed(
    fake_redis, s3_settings, library, fake_pg
):
    """Incremental is the whole point of the manifest.

    Without it every scheduled run re-uploads the entire library, which for a
    26,000-track collection is the difference between pennies and real money.
    """
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)

    first = _service().run_backup()
    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)
    second = _service().run_backup()

    assert first.get("files_uploaded", 0) >= 2
    assert second.get("files_skipped", 0) >= 2, second
    assert second.get("files_uploaded", 0) == 0, "re-uploaded unchanged audio"


@mock_aws
def test_a_changed_file_is_uploaded_again_under_its_new_hash(
    fake_redis, s3_settings, library, fake_pg
):
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()
    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)

    # Rewrite one file and re-point the row at its new hash.
    changed = Path(library.tracks[0]["file_path"])
    new_content = b"RIFF-one-CHANGED" + b"z" * 500
    changed.write_bytes(new_content)
    new_hash = hashlib.sha256(new_content).hexdigest()

    rows = [dict(t) for t in library.tracks]
    rows[0]["file_hash"] = new_hash
    rows[0]["file_size"] = len(new_content)
    _write_tracks(library.db_url, rows)
    second = _service().run_backup()

    keys = {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])}
    assert f"audio/{new_hash[:4]}/{new_hash}.flac" in keys
    assert second.get("files_uploaded", 0) >= 1


@mock_aws
def test_two_backups_cannot_run_at_once(fake_redis, s3_settings, library, fake_pg):
    """The lock is 24 hours; without it a slow run and the scheduler overlap."""
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    fake_redis.set(s3mod.REDIS_BACKUP_LOCK, "1", nx=True)

    result = _service().run_backup()
    assert result.get("status") in ("already_running", "error"), result


# --- restore ----------------------------------------------------------------


@mock_aws
def test_restore_asks_glacier_to_thaw_before_anything_is_downloaded(
    fake_redis, s3_settings, library, fake_pg
):
    """Deep Archive cannot be read directly — a restore that skips this gets 403."""
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()

    result = _service().initiate_restore()
    assert result.get("files_requested", 0) >= 2, result


@mock_aws
def test_backup_then_restore_returns_the_original_bytes(fake_redis, s3_settings, library, fake_pg):
    """The question a backup exists to answer, and the one never asked before.

    Deletes the local audio after backing up, then restores and compares bytes.
    """
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    original = {t["file_path"]: Path(t["file_path"]).read_bytes() for t in library.tracks}

    _service().run_backup()
    _service().initiate_restore()

    for path in original:
        Path(path).unlink()
        assert not Path(path).exists()

    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)
    result = _service().download_and_restore()
    assert result.get("status") != "error", result

    for path, content in original.items():
        assert Path(path).exists(), f"{path} was not restored"
        assert Path(path).read_bytes() == content, f"{path} restored corrupted"


@mock_aws
def test_restore_reapplies_the_database_dump(fake_redis, s3_settings, library, fake_pg):
    """The audio is worthless without the library that indexes it."""
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()
    _service().initiate_restore()
    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)

    _service().download_and_restore()
    assert fake_pg.restored.get("bytes") == fake_pg.payload


# --- credentials and cost ---------------------------------------------------


@mock_aws
def test_validate_reports_success_against_a_reachable_bucket(fake_redis, s3_settings):
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    result = _service().validate_credentials(
        bucket=BUCKET,
        region=REGION,
        access_key_id="testing",
        secret_access_key="testing",
    )
    assert result.get("valid") is True, result


@mock_aws
def test_validate_fails_on_a_bucket_that_does_not_exist(fake_redis, s3_settings):
    result = _service().validate_credentials(
        bucket="no-such-bucket-familiar",
        region=REGION,
        access_key_id="testing",
        secret_access_key="testing",
    )
    assert result.get("valid") is False
    assert result.get("error")


# --- the safety dump -------------------------------------------------------


@mock_aws
def test_restore_writes_a_local_safety_dump_before_overwriting_the_database(
    fake_redis, s3_settings, library, fake_pg
):
    """`download_and_restore` runs psql against the live database.

    The endpoint docstring promised "creates a local safety backup first" and
    nothing produced one, so the operation had no undo. This pins the promise.
    """
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()
    _service().initiate_restore()
    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)

    _service().download_and_restore()

    dumps = sorted((library.root / "data" / "restore-safety").glob("pre-restore_*.sql.gz"))
    assert dumps, "no safety dump was written before the restore"
    assert dumps[0].stat().st_size > 0


@mock_aws
def test_a_restore_aborts_when_the_safety_dump_fails(fake_redis, s3_settings, library, fake_pg):
    """Refusing the restore beats running it with no way back.

    The worst available failure mode is skipping the safety net silently and
    letting psql overwrite the database anyway.
    """
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()
    _service().initiate_restore()
    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)

    def boom(self, out_path):
        raise RuntimeError("pg_dump: connection refused")

    with patch.object(s3mod.S3BackupService, "_pg_dump_to", boom):
        result = _service().download_and_restore()

    assert result.get("status") == "error", result
    assert "safety dump" in (result.get("error") or "").lower()
    assert fake_pg.restored == {}, "database was overwritten despite no safety dump"


@mock_aws
def test_the_safety_dump_stays_local_rather_than_going_to_glacier(
    fake_redis, s3_settings, library, fake_pg
):
    """A safety copy behind a 12-48 hour thaw is not a safety copy.

    The restore is already running because S3 is being read, so the undo has to
    be reachable without S3 at all.
    """
    client = boto3.client("s3", region_name=REGION)
    _bucket(client)
    _service().run_backup()
    _service().initiate_restore()
    fake_redis.kv.pop(s3mod.REDIS_BACKUP_LOCK, None)

    before = {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])}
    _service().download_and_restore()
    after = {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])}

    assert after == before, "the safety dump was uploaded instead of kept local"
    assert (library.root / "data" / "restore-safety").is_dir()
