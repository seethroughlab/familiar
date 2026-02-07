"""S3 Glacier Deep Archive backup service.

Provides periodic backup of the entire Familiar installation to S3:
- Database (pg_dump) → S3 Standard (small, need quick access)
- Settings → S3 Standard
- Audio files → DEEP_ARCHIVE (content-addressed by file_hash)
- Artwork, videos, profiles → DEEP_ARCHIVE
- Manifest → S3 Standard (instant read for incremental backup)

Uses boto3 in a thread executor (synchronous I/O, runs in background).
"""

import asyncio
import gzip
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import settings as app_config
from app.services.app_settings import get_app_settings_service
from app.services.redis_client import get_resilient_redis

logger = logging.getLogger(__name__)

# Redis keys
REDIS_BACKUP_PROGRESS = "familiar:s3backup:progress"
REDIS_BACKUP_LOCK = "familiar:s3backup:lock"
REDIS_BACKUP_HISTORY = "familiar:s3backup:history"
REDIS_RESTORE_STATE = "familiar:s3backup:restore"

# S3 pricing (us-east-1, as of 2024)
DEEP_ARCHIVE_STORAGE_PER_GB_MONTH = 0.00099
DEEP_ARCHIVE_PUT_PER_1K = 0.05
DEEP_ARCHIVE_RETRIEVAL_PER_GB = 0.0025
STANDARD_STORAGE_PER_GB_MONTH = 0.023


def _get_boto3_client(
    region: str,
    access_key_id: str,
    secret_access_key: str,
    service: str = "s3",
):
    """Create a boto3 client. Must be called in a thread (synchronous)."""
    import boto3

    return boto3.client(
        service,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def _s3_key(prefix: str, path: str) -> str:
    """Build an S3 key with optional prefix."""
    if prefix:
        return f"{prefix.strip('/')}/{path}"
    return path


def _hash_file(filepath: Path) -> str:
    """SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class BackupProgressReporter:
    """Reports backup progress via Redis (matches SyncProgressReporter pattern)."""

    def __init__(self):
        self._redis = get_resilient_redis()
        self._data: dict[str, Any] = {
            "status": "starting",
            "phase": "starting",
            "files_total": 0,
            "files_uploaded": 0,
            "files_skipped": 0,
            "bytes_uploaded": 0,
            "current_file": None,
            "started_at": datetime.utcnow().isoformat(),
            "error": None,
        }
        self._flush()

    def _flush(self) -> None:
        try:
            self._redis.set(REDIS_BACKUP_PROGRESS, json.dumps(self._data), ex=86400)
        except Exception:
            pass

    def update(self, **kwargs: Any) -> None:
        self._data.update(kwargs)
        self._flush()

    def get(self) -> dict[str, Any]:
        return dict(self._data)


class S3BackupService:
    """Service for S3 Glacier Deep Archive backups."""

    def _get_settings(self) -> dict[str, Any]:
        """Get S3 backup settings.

        Uses get_effective() for credentials and bucket/region/prefix
        to support env var fallback (settings.json > env var > default).
        """
        svc = get_app_settings_service()
        s = svc.get()
        return {
            "enabled": s.s3_backup_enabled,
            "bucket": svc.get_effective("s3_backup_bucket"),
            "region": svc.get_effective("s3_backup_region") or "us-east-1",
            "access_key_id": svc.get_effective("s3_backup_access_key_id"),
            "secret_access_key": svc.get_effective("s3_backup_secret_access_key"),
            "prefix": svc.get_effective("s3_backup_prefix") or "",
            "schedule": s.s3_backup_schedule,
        }

    def _get_client(self, cfg: dict[str, Any] | None = None):
        """Get a boto3 S3 client from current settings."""
        if cfg is None:
            cfg = self._get_settings()
        return _get_boto3_client(
            region=cfg["region"],
            access_key_id=cfg["access_key_id"],
            secret_access_key=cfg["secret_access_key"],
        )

    def _ensure_bucket(self, client: Any, bucket: str, region: str) -> None:
        """Create S3 bucket if it doesn't exist."""
        from botocore.exceptions import ClientError

        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket"):
                logger.info(f"Creating S3 bucket: {bucket} in {region}")
                if region == "us-east-1":
                    client.create_bucket(Bucket=bucket)
                else:
                    client.create_bucket(
                        Bucket=bucket,
                        CreateBucketConfiguration={"LocationConstraint": region},
                    )
            else:
                raise

    # ── Phase 1: Validation & Cost Estimate ──────────────────────────

    def validate_credentials(
        self,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str = "",
    ) -> dict[str, Any]:
        """Validate AWS credentials and required permissions.

        Tests: PutObject (DEEP_ARCHIVE), GetObject, ListObjectsV2, RestoreObject.
        Uses a small test object and cleans up after.
        """
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        result: dict[str, Any] = {
            "valid": False,
            "permissions": {
                "put": False,
                "get": False,
                "list": False,
                "restore": False,
            },
            "error": None,
        }

        try:
            client = boto3.client(
                "s3",
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
            )
        except NoCredentialsError as e:
            result["error"] = f"Invalid credentials: {e}"
            return result

        test_key = _s3_key(prefix, "_familiar_test_object")
        test_body = b"familiar-backup-validation-test"

        # Ensure bucket exists (or can be accessed)
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "404":
                result["error"] = f"Bucket '{bucket}' does not exist"
            elif code == "403":
                result["error"] = f"Access denied to bucket '{bucket}'"
            else:
                result["error"] = f"Cannot access bucket: {e}"
            return result

        # Test PutObject with DEEP_ARCHIVE
        try:
            client.put_object(
                Bucket=bucket,
                Key=test_key,
                Body=test_body,
                StorageClass="DEEP_ARCHIVE",
            )
            result["permissions"]["put"] = True
        except ClientError as e:
            result["error"] = f"PutObject failed: {e}"

        # Test ListObjectsV2
        try:
            client.list_objects_v2(
                Bucket=bucket,
                Prefix=_s3_key(prefix, "_familiar_test"),
                MaxKeys=1,
            )
            result["permissions"]["list"] = True
        except ClientError:
            pass

        # Test GetObject
        if result["permissions"]["put"]:
            try:
                client.get_object(Bucket=bucket, Key=test_key)
                result["permissions"]["get"] = True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                # InvalidObjectState means permission works, just can't GET from DEEP_ARCHIVE directly
                if code == "InvalidObjectState":
                    result["permissions"]["get"] = True

        # Test RestoreObject (will fail with InvalidObjectState since not in Glacier yet,
        # but a 403 would indicate missing permission)
        if result["permissions"]["put"]:
            try:
                client.restore_object(
                    Bucket=bucket,
                    Key=test_key,
                    RestoreRequest={"Days": 1, "GlacierJobParameters": {"Tier": "Bulk"}},
                )
                result["permissions"]["restore"] = True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                # InvalidObjectState means the permission works, just not applicable yet
                if code == "InvalidObjectState":
                    result["permissions"]["restore"] = True

        # Cleanup test object
        try:
            client.delete_object(Bucket=bucket, Key=test_key)
        except Exception:
            pass

        result["valid"] = all(result["permissions"].values())
        return result

    def estimate_cost(self) -> dict[str, Any]:
        """Estimate backup costs based on actual library data sizes.

        Scans local data to calculate S3 Glacier Deep Archive pricing.
        Does not require AWS credentials.
        """
        from sqlalchemy import create_engine, text

        categories: dict[str, dict[str, Any]] = {}

        # Audio files — query DB for track count and file sizes
        audio_size = 0
        audio_count = 0
        try:
            engine = create_engine(app_config.sync_database_url)
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM tracks WHERE file_size IS NOT NULL")
                ).fetchone()
                if row:
                    audio_count = int(row[0] or 0)
                    audio_size = int(row[1] or 0)
            engine.dispose()
        except Exception as e:
            logger.warning(f"Failed to query track sizes: {e}")

        audio_size_gb = audio_size / (1024**3)
        categories["audio"] = {
            "file_count": audio_count,
            "size_bytes": audio_size,
            "size_gb": round(audio_size_gb, 2),
            "monthly_cost": round(audio_size_gb * DEEP_ARCHIVE_STORAGE_PER_GB_MONTH, 4),
        }

        # Artwork, videos, profiles
        for name, path_attr in [
            ("artwork", app_config.art_path),
            ("videos", app_config.videos_path),
            ("profiles", app_config.profiles_path),
        ]:
            total_size = 0
            file_count = 0
            try:
                p = Path(path_attr)
                if p.exists():
                    for f in p.rglob("*"):
                        if f.is_file():
                            total_size += f.stat().st_size
                            file_count += 1
            except Exception as e:
                logger.warning(f"Failed to scan {name}: {e}")

            size_gb = total_size / (1024**3)
            categories[name] = {
                "file_count": file_count,
                "size_bytes": total_size,
                "size_gb": round(size_gb, 2),
                "monthly_cost": round(size_gb * DEEP_ARCHIVE_STORAGE_PER_GB_MONTH, 4),
            }

        # Database (estimate from DB stats)
        db_size = 0
        try:
            engine = create_engine(app_config.sync_database_url)
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT pg_database_size(current_database())")
                ).fetchone()
                if row:
                    db_size = row[0] or 0
            engine.dispose()
        except Exception as e:
            logger.warning(f"Failed to estimate DB size: {e}")

        # pg_dump + gzip is typically 10-30% of raw DB size
        estimated_dump_size = int(db_size * 0.2)
        dump_gb = estimated_dump_size / (1024**3)
        categories["database"] = {
            "size_bytes": estimated_dump_size,
            "size_gb": round(dump_gb, 2),
            "monthly_cost": round(dump_gb * STANDARD_STORAGE_PER_GB_MONTH, 4),
        }

        # Settings (tiny)
        settings_path = Path("data/settings.json")
        settings_size = settings_path.stat().st_size if settings_path.exists() else 0
        categories["settings"] = {
            "size_bytes": settings_size,
            "size_gb": round(settings_size / (1024**3), 6),
            "monthly_cost": 0.0,
        }

        # Totals
        total_size_bytes = sum(c["size_bytes"] for c in categories.values())
        total_size_gb = total_size_bytes / (1024**3)
        total_monthly = sum(c["monthly_cost"] for c in categories.values())
        total_file_count = sum(c.get("file_count", 0) for c in categories.values())

        # Initial upload cost (PUT requests)
        initial_put_cost = (total_file_count / 1000) * DEEP_ARCHIVE_PUT_PER_1K

        # Estimated full restore cost (retrieval + GET)
        glacier_size_gb = sum(
            c["size_gb"] for name, c in categories.items()
            if name not in ("database", "settings")
        )
        estimated_restore_cost = glacier_size_gb * DEEP_ARCHIVE_RETRIEVAL_PER_GB

        return {
            "storage_gb": round(total_size_gb, 2),
            "monthly_cost": round(total_monthly, 4),
            "initial_upload_cost": round(initial_put_cost, 2),
            "estimated_restore_cost": round(estimated_restore_cost, 2),
            "by_category": categories,
        }

    # ── Phase 2: Manual Backup ───────────────────────────────────────

    def run_backup(self) -> dict[str, Any]:
        """Full backup orchestration. Runs synchronously in a thread executor.

        1. Download existing manifest (if any)
        2. pg_dump → gzip → upload to S3 Standard
        3. Upload settings.json to S3 Standard
        4. Upload new/changed audio files to DEEP_ARCHIVE
        5. Upload new/changed artwork, videos, profiles to DEEP_ARCHIVE
        6. Write updated manifest to S3 Standard
        """
        import boto3.s3.transfer
        from botocore.exceptions import ClientError
        from sqlalchemy import create_engine, text

        cfg = self._get_settings()
        if not cfg["enabled"] or not cfg["bucket"] or not cfg["access_key_id"]:
            return {"status": "error", "error": "S3 backup not configured"}

        redis = get_resilient_redis()

        # Acquire lock
        if not redis.set(REDIS_BACKUP_LOCK, "1", nx=True, ex=86400):
            return {"status": "error", "error": "Backup already running"}

        progress = BackupProgressReporter()
        start_time = time.monotonic()
        manifest: dict[str, Any] = {"version": 1, "files": {}}

        try:
            client = self._get_client(cfg)
            bucket = cfg["bucket"]
            prefix = cfg["prefix"]
            region = cfg["region"]

            # Create bucket if it doesn't exist
            self._ensure_bucket(client, bucket, region)

            # Load existing manifest
            progress.update(phase="manifest", status="running")
            manifest = self._load_manifest(client, bucket, prefix)

            # Phase: Database
            progress.update(phase="database", current_file="pg_dump")
            db_key, db_size, db_checksum = self._backup_database(client, bucket, prefix)
            manifest["database"] = {
                "s3_key": db_key,
                "size_bytes": db_size,
                "checksum": db_checksum,
                "backed_up_at": datetime.utcnow().isoformat(),
            }
            progress.update(bytes_uploaded=progress.get()["bytes_uploaded"] + db_size)

            # Phase: Settings
            progress.update(phase="settings", current_file="settings.json")
            settings_path = Path("data/settings.json")
            if settings_path.exists():
                s_key = _s3_key(prefix, "settings.json")
                client.upload_file(
                    str(settings_path), bucket, s_key,
                    ExtraArgs={"StorageClass": "STANDARD"},
                )
                manifest["settings"] = {
                    "s3_key": s_key,
                    "size_bytes": settings_path.stat().st_size,
                }

            # Phase: Audio files
            progress.update(phase="audio")
            engine = create_engine(app_config.sync_database_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT id, file_path, file_hash, file_size FROM tracks WHERE file_hash IS NOT NULL")
                ).fetchall()
            engine.dispose()

            progress.update(files_total=len(rows))
            transfer_config = boto3.s3.transfer.TransferConfig(
                multipart_threshold=100 * 1024 * 1024,  # 100MB
                max_concurrency=4,
            )

            existing_files = manifest.get("files", {})
            uploaded = 0
            skipped = 0
            total_bytes = progress.get()["bytes_uploaded"]

            for row in rows:
                track_id, file_path, file_hash, file_size = row
                if not file_hash or not file_path:
                    skipped += 1
                    continue

                fp = Path(file_path)
                if not fp.exists():
                    skipped += 1
                    continue

                ext = fp.suffix.lower()
                hash_prefix = file_hash[:4]
                s3_path = f"audio/{hash_prefix}/{file_hash}{ext}"
                s3_full_key = _s3_key(prefix, s3_path)

                # Skip if already in manifest with same hash
                if s3_path in existing_files:
                    existing = existing_files[s3_path]
                    if existing.get("file_hash") == f"sha256:{file_hash}":
                        skipped += 1
                        progress.update(files_skipped=skipped)
                        continue

                progress.update(current_file=fp.name)

                try:
                    client.upload_file(
                        str(fp), bucket, s3_full_key,
                        ExtraArgs={"StorageClass": "DEEP_ARCHIVE"},
                        Config=transfer_config,
                    )
                    actual_size = file_size or fp.stat().st_size
                    manifest["files"][s3_path] = {
                        "source_path": str(file_path),
                        "file_hash": f"sha256:{file_hash}",
                        "size_bytes": actual_size,
                        "storage_class": "DEEP_ARCHIVE",
                    }
                    uploaded += 1
                    total_bytes += actual_size
                    progress.update(
                        files_uploaded=uploaded,
                        bytes_uploaded=total_bytes,
                    )
                except Exception as e:
                    logger.error(f"Failed to upload {fp.name}: {e}")

                # Check for cancellation
                cancel_data = redis.get(f"{REDIS_BACKUP_LOCK}:cancel")
                if cancel_data:
                    redis.delete(f"{REDIS_BACKUP_LOCK}:cancel")
                    progress.update(phase="cancelled", status="cancelled")
                    return {"status": "cancelled"}

            # Phase: Artwork
            progress.update(phase="artwork")
            self._backup_directory(
                client, bucket, prefix, Path(app_config.art_path),
                "artwork", manifest, progress, transfer_config,
            )

            # Phase: Videos
            progress.update(phase="videos")
            self._backup_directory(
                client, bucket, prefix, Path(app_config.videos_path),
                "videos", manifest, progress, transfer_config,
            )

            # Phase: Profiles
            progress.update(phase="profiles")
            self._backup_directory(
                client, bucket, prefix, Path(app_config.profiles_path),
                "profiles", manifest, progress, transfer_config,
            )

            # Write manifest
            progress.update(phase="manifest", current_file="manifest.json")
            manifest["last_backup_at"] = datetime.utcnow().isoformat()
            self._save_manifest(client, bucket, prefix, manifest)

            duration = time.monotonic() - start_time
            final = progress.get()
            progress.update(phase="complete", status="complete", current_file=None)

            # Save to history
            self._save_history_entry({
                "timestamp": datetime.utcnow().isoformat(),
                "duration_seconds": round(duration, 1),
                "files_uploaded": final["files_uploaded"],
                "files_skipped": final["files_skipped"],
                "bytes_uploaded": final["bytes_uploaded"],
                "status": "success",
            })

            return {
                "status": "success",
                "files_uploaded": final["files_uploaded"],
                "files_skipped": final["files_skipped"],
                "bytes_uploaded": final["bytes_uploaded"],
                "duration_seconds": round(duration, 1),
            }

        except Exception as e:
            logger.error(f"Backup failed: {e}", exc_info=True)
            progress.update(phase="error", status="error", error=str(e))
            self._save_history_entry({
                "timestamp": datetime.utcnow().isoformat(),
                "duration_seconds": round(time.monotonic() - start_time, 1),
                "files_uploaded": progress.get()["files_uploaded"],
                "files_skipped": progress.get()["files_skipped"],
                "bytes_uploaded": progress.get()["bytes_uploaded"],
                "status": "error",
                "error": str(e),
            })
            return {"status": "error", "error": str(e)}
        finally:
            try:
                redis.delete(REDIS_BACKUP_LOCK)
            except Exception:
                pass

    def _backup_database(
        self, client: Any, bucket: str, prefix: str
    ) -> tuple[str, int, str]:
        """Run pg_dump, gzip, upload to S3 Standard. Returns (key, size, checksum)."""
        db_url = app_config.sync_database_url
        # Parse connection string for pg_dump
        # Format: postgresql://user:pass@host:port/dbname
        from urllib.parse import urlparse

        parsed = urlparse(db_url)

        env = os.environ.copy()
        if parsed.password:
            env["PGPASSWORD"] = parsed.password

        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # pg_dump | gzip
            pg_dump_cmd = [
                "pg_dump",
                "-h", parsed.hostname or "localhost",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "familiar",
                "-d", parsed.path.lstrip("/") if parsed.path else "familiar",
                "--no-owner",
                "--no-acl",
            ]

            with open(tmp_path, "wb") as out_f:
                dump_proc = subprocess.Popen(
                    pg_dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
                )
                with gzip.open(out_f, "wb") as gz:
                    while True:
                        chunk = dump_proc.stdout.read(65536)
                        if not chunk:
                            break
                        gz.write(chunk)

                dump_proc.wait()
                if dump_proc.returncode != 0:
                    stderr = dump_proc.stderr.read().decode() if dump_proc.stderr else ""
                    raise RuntimeError(f"pg_dump failed: {stderr}")

            size = os.path.getsize(tmp_path)
            checksum = _hash_file(Path(tmp_path))

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            s3_key = _s3_key(prefix, f"database/familiar_{timestamp}.sql.gz")

            client.upload_file(
                tmp_path, bucket, s3_key,
                ExtraArgs={"StorageClass": "STANDARD"},
            )

            return s3_key, size, f"sha256:{checksum}"
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _backup_directory(
        self,
        client: Any,
        bucket: str,
        prefix: str,
        local_dir: Path,
        category: str,
        manifest: dict[str, Any],
        progress: BackupProgressReporter,
        transfer_config: Any,
    ) -> None:
        """Back up a directory to S3, hashing files for dedup."""
        if not local_dir.exists():
            return

        redis = get_resilient_redis()
        existing_files = manifest.get("files", {})

        for filepath in local_dir.rglob("*"):
            if not filepath.is_file():
                continue

            # Use relative path within category
            rel_path = filepath.relative_to(local_dir)
            file_hash = _hash_file(filepath)
            s3_path = f"{category}/{file_hash[:4]}/{file_hash}{filepath.suffix}"
            s3_full_key = _s3_key(prefix, s3_path)

            # Skip if already backed up
            if s3_path in existing_files:
                existing = existing_files[s3_path]
                if existing.get("file_hash") == f"sha256:{file_hash}":
                    cur = progress.get()
                    progress.update(files_skipped=cur["files_skipped"] + 1)
                    continue

            progress.update(current_file=str(rel_path))

            try:
                client.upload_file(
                    str(filepath), bucket, s3_full_key,
                    ExtraArgs={"StorageClass": "DEEP_ARCHIVE"},
                    Config=transfer_config,
                )
                file_size = filepath.stat().st_size
                manifest["files"][s3_path] = {
                    "source_path": str(rel_path),
                    "file_hash": f"sha256:{file_hash}",
                    "size_bytes": file_size,
                    "storage_class": "DEEP_ARCHIVE",
                    "category": category,
                }
                cur = progress.get()
                progress.update(
                    files_uploaded=cur["files_uploaded"] + 1,
                    bytes_uploaded=cur["bytes_uploaded"] + file_size,
                )
            except Exception as e:
                logger.error(f"Failed to upload {category}/{rel_path}: {e}")

            # Check for cancellation
            cancel_data = redis.get(f"{REDIS_BACKUP_LOCK}:cancel")
            if cancel_data:
                return

    def cancel_backup(self) -> bool:
        """Signal a running backup to cancel."""
        redis = get_resilient_redis()
        if redis.get(REDIS_BACKUP_LOCK):
            redis.set(f"{REDIS_BACKUP_LOCK}:cancel", "1", ex=60)
            return True
        return False

    # ── Manifest ─────────────────────────────────────────────────────

    def _load_manifest(self, client: Any, bucket: str, prefix: str) -> dict[str, Any]:
        """Download manifest from S3 Standard. Returns empty manifest if none exists."""
        from botocore.exceptions import ClientError

        key = _s3_key(prefix, "manifest.json")
        try:
            resp = client.get_object(Bucket=bucket, Key=key)
            data = json.loads(resp["Body"].read().decode("utf-8"))
            return data
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                return {"version": 1, "files": {}}
            raise

    def _save_manifest(
        self, client: Any, bucket: str, prefix: str, manifest: dict[str, Any]
    ) -> None:
        """Write manifest to S3 Standard."""
        key = _s3_key(prefix, "manifest.json")
        body = json.dumps(manifest, indent=2).encode("utf-8")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            StorageClass="STANDARD",
            ContentType="application/json",
        )

    # ── Phase 2: Progress ────────────────────────────────────────────

    def get_backup_progress(self) -> dict[str, Any] | None:
        """Get current backup progress from Redis."""
        redis = get_resilient_redis()
        try:
            data = redis.get(REDIS_BACKUP_PROGRESS)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    # ── Phase 3: History & Status ────────────────────────────────────

    def _save_history_entry(self, entry: dict[str, Any]) -> None:
        """Save a backup result to history list in Redis."""
        redis = get_resilient_redis()
        try:
            redis.lpush(REDIS_BACKUP_HISTORY, json.dumps(entry))
            redis.ltrim(REDIS_BACKUP_HISTORY, 0, 9)  # Keep last 10
            redis.expire(REDIS_BACKUP_HISTORY, 30 * 86400)  # 30-day TTL
        except Exception as e:
            logger.warning(f"Failed to save backup history: {e}")

    def get_backup_history(self) -> list[dict[str, Any]]:
        """Get backup history (last 10 runs)."""
        redis = get_resilient_redis()
        try:
            items = redis.lrange(REDIS_BACKUP_HISTORY, 0, 9)
            return [json.loads(item) for item in items]
        except Exception:
            return []

    def get_status(self) -> dict[str, Any]:
        """Get backup status: enabled, last backup, next scheduled."""
        cfg = self._get_settings()
        history = self.get_backup_history()
        progress = self.get_backup_progress()

        is_running = False
        if progress:
            is_running = progress.get("status") == "running"

        last_backup = history[0] if history else None

        return {
            "enabled": cfg["enabled"],
            "bucket": cfg["bucket"],
            "region": cfg["region"],
            "schedule": cfg["schedule"],
            "is_running": is_running,
            "last_backup": last_backup,
            "progress": progress if is_running else None,
        }

    # ── Phase 4: Restore — Initiation ────────────────────────────────

    def get_manifest(self) -> dict[str, Any]:
        """Download and parse manifest from S3 (instant, stored in Standard)."""
        cfg = self._get_settings()
        client = self._get_client(cfg)
        manifest = self._load_manifest(client, cfg["bucket"], cfg["prefix"])

        # Build summary
        file_count = len(manifest.get("files", {}))
        total_size = sum(f.get("size_bytes", 0) for f in manifest.get("files", {}).values())

        categories: dict[str, dict[str, int]] = {}
        for path, info in manifest.get("files", {}).items():
            cat = path.split("/")[0] if "/" in path else "other"
            if cat not in categories:
                categories[cat] = {"count": 0, "size_bytes": 0}
            categories[cat]["count"] += 1
            categories[cat]["size_bytes"] += info.get("size_bytes", 0)

        return {
            "last_backup_at": manifest.get("last_backup_at"),
            "database": manifest.get("database"),
            "settings": manifest.get("settings"),
            "file_count": file_count,
            "total_size_bytes": total_size,
            "by_category": categories,
        }

    def initiate_restore(self, categories: list[str] | None = None) -> dict[str, Any]:
        """Send RestoreObject requests for Glacier files. Uses Bulk tier (cheapest, 12-48hr).

        Args:
            categories: Which categories to restore (e.g., ["audio", "artwork"]).
                        None = all.
        """
        from botocore.exceptions import ClientError

        cfg = self._get_settings()
        client = self._get_client(cfg)
        manifest = self._load_manifest(client, cfg["bucket"], cfg["prefix"])
        files = manifest.get("files", {})

        # Filter by category
        if categories:
            files = {
                k: v for k, v in files.items()
                if any(k.startswith(cat + "/") for cat in categories)
            }

        total = len(files)
        requested = 0
        already_available = 0
        errors = 0

        for s3_path, info in files.items():
            if info.get("storage_class") != "DEEP_ARCHIVE":
                continue

            s3_key = _s3_key(cfg["prefix"], s3_path)
            try:
                client.restore_object(
                    Bucket=cfg["bucket"],
                    Key=s3_key,
                    RestoreRequest={
                        "Days": 7,  # Keep available for 7 days
                        "GlacierJobParameters": {"Tier": "Bulk"},
                    },
                )
                requested += 1
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code == "RestoreAlreadyInProgress":
                    requested += 1  # Already requested
                elif code == "InvalidObjectState":
                    already_available += 1  # Already restored/available
                else:
                    logger.error(f"RestoreObject failed for {s3_path}: {e}")
                    errors += 1

        # Save restore state to Redis
        redis = get_resilient_redis()
        state = {
            "status": "retrieving",
            "initiated_at": datetime.utcnow().isoformat(),
            "total_files": total,
            "files_requested": requested,
            "files_available": already_available,
            "errors": errors,
            "categories": categories or ["all"],
        }
        redis.set(REDIS_RESTORE_STATE, json.dumps(state), ex=7 * 86400)

        return state

    def check_restore_status(self) -> dict[str, Any]:
        """Check Glacier retrieval status by HEAD-requesting a sample of objects."""
        from botocore.exceptions import ClientError

        redis = get_resilient_redis()
        state_data = redis.get(REDIS_RESTORE_STATE)
        if not state_data:
            return {"status": "none"}

        state = json.loads(state_data)
        if state["status"] in ("complete", "downloading"):
            return state

        cfg = self._get_settings()
        client = self._get_client(cfg)
        manifest = self._load_manifest(client, cfg["bucket"], cfg["prefix"])

        files = manifest.get("files", {})
        categories = state.get("categories", ["all"])
        if "all" not in categories:
            files = {
                k: v for k, v in files.items()
                if any(k.startswith(cat + "/") for cat in categories)
            }

        glacier_files = {
            k: v for k, v in files.items()
            if v.get("storage_class") == "DEEP_ARCHIVE"
        }

        if not glacier_files:
            state["status"] = "available"
            redis.set(REDIS_RESTORE_STATE, json.dumps(state), ex=7 * 86400)
            return state

        # Sample up to 20 files to check
        sample_keys = list(glacier_files.keys())[:20]
        available_count = 0

        for s3_path in sample_keys:
            s3_key = _s3_key(cfg["prefix"], s3_path)
            try:
                resp = client.head_object(Bucket=cfg["bucket"], Key=s3_key)
                restore_header = resp.get("Restore", "")
                if 'ongoing-request="false"' in restore_header:
                    available_count += 1
            except ClientError:
                pass

        # If all sampled files are available, mark as available
        if available_count == len(sample_keys):
            state["status"] = "available"
            state["files_available"] = state["total_files"]
        else:
            # Estimate progress from sample
            pct = available_count / len(sample_keys) if sample_keys else 0
            state["files_available"] = int(state["total_files"] * pct)

        redis.set(REDIS_RESTORE_STATE, json.dumps(state), ex=7 * 86400)
        return state

    # ── Phase 5: Restore — Download & Apply ──────────────────────────

    def download_and_restore(self) -> dict[str, Any]:
        """Download restored files from S3 and apply. Runs synchronously in thread executor.

        1. Download + apply pg_dump (restore DB)
        2. Download settings.json
        3. Download audio files to original paths (skip if local hash matches)
        4. Download artwork, videos, profile avatars
        """
        from botocore.exceptions import ClientError

        cfg = self._get_settings()
        client = self._get_client(cfg)
        bucket = cfg["bucket"]
        prefix = cfg["prefix"]
        manifest = self._load_manifest(client, bucket, prefix)

        redis = get_resilient_redis()
        progress = BackupProgressReporter()
        progress.update(phase="starting", status="running")
        start_time = time.monotonic()

        try:
            # Phase: Database
            db_info = manifest.get("database")
            if db_info:
                progress.update(phase="database", current_file="pg_dump restore")
                self._restore_database(client, bucket, db_info["s3_key"])

            # Phase: Settings
            settings_info = manifest.get("settings")
            if settings_info:
                progress.update(phase="settings", current_file="settings.json")
                resp = client.get_object(Bucket=bucket, Key=settings_info["s3_key"])
                settings_data = resp["Body"].read()
                settings_path = Path("data/settings.json")
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_bytes(settings_data)

            # Phase: Files
            files = manifest.get("files", {})
            total_files = len(files)
            downloaded = 0
            skipped = 0

            progress.update(phase="downloading", files_total=total_files)

            for s3_path, info in files.items():
                category = s3_path.split("/")[0] if "/" in s3_path else "other"
                source_path = info.get("source_path", "")
                file_hash = info.get("file_hash", "")

                # Determine local path
                if category == "audio":
                    local_path = Path(source_path) if source_path else None
                elif category in ("artwork", "videos", "profiles"):
                    dir_map = {
                        "artwork": app_config.art_path,
                        "videos": app_config.videos_path,
                        "profiles": app_config.profiles_path,
                    }
                    base_dir = Path(dir_map.get(category, "data"))
                    local_path = base_dir / source_path if source_path else None
                else:
                    local_path = None

                if not local_path:
                    skipped += 1
                    continue

                # Skip if local file exists and hash matches
                if local_path.exists() and file_hash:
                    hash_val = file_hash.replace("sha256:", "")
                    if _hash_file(local_path) == hash_val:
                        skipped += 1
                        progress.update(files_skipped=skipped)
                        continue

                progress.update(current_file=local_path.name)
                s3_key = _s3_key(prefix, s3_path)

                try:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    client.download_file(bucket, s3_key, str(local_path))
                    downloaded += 1
                    cur = progress.get()
                    progress.update(
                        files_uploaded=downloaded,  # reuse field for download count
                        bytes_uploaded=cur["bytes_uploaded"] + info.get("size_bytes", 0),
                    )
                except ClientError as e:
                    logger.error(f"Failed to download {s3_path}: {e}")

            duration = time.monotonic() - start_time
            progress.update(phase="complete", status="complete", current_file=None)

            # Update restore state
            state = {"status": "complete", "completed_at": datetime.utcnow().isoformat()}
            redis.set(REDIS_RESTORE_STATE, json.dumps(state), ex=7 * 86400)

            return {
                "status": "success",
                "files_downloaded": downloaded,
                "files_skipped": skipped,
                "duration_seconds": round(duration, 1),
            }

        except Exception as e:
            logger.error(f"Restore failed: {e}", exc_info=True)
            progress.update(phase="error", status="error", error=str(e))
            return {"status": "error", "error": str(e)}

    def _restore_database(self, client: Any, bucket: str, s3_key: str) -> None:
        """Download and restore a pg_dump backup."""
        from urllib.parse import urlparse

        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            client.download_file(bucket, s3_key, tmp_path)

            db_url = app_config.sync_database_url
            parsed = urlparse(db_url)

            env = os.environ.copy()
            if parsed.password:
                env["PGPASSWORD"] = parsed.password

            # Decompress and restore
            with gzip.open(tmp_path, "rb") as gz:
                sql_data = gz.read()

            restore_cmd = [
                "psql",
                "-h", parsed.hostname or "localhost",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "familiar",
                "-d", parsed.path.lstrip("/") if parsed.path else "familiar",
            ]

            proc = subprocess.run(
                restore_cmd,
                input=sql_data,
                capture_output=True,
                env=env,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode() if proc.stderr else ""
                logger.warning(f"psql restore warnings: {stderr}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def get_restore_status(self) -> dict[str, Any]:
        """Get restore state from Redis."""
        redis = get_resilient_redis()
        try:
            data = redis.get(REDIS_RESTORE_STATE)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return {"status": "none"}


# Singleton
_s3_backup_service: S3BackupService | None = None


def get_s3_backup_service() -> S3BackupService:
    global _s3_backup_service
    if _s3_backup_service is None:
        _s3_backup_service = S3BackupService()
    return _s3_backup_service
