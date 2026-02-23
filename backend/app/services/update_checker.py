"""Check GitHub releases for available updates.

Fetches releases from the GitHub API, filters by the user's chosen channel
(stable, beta, alpha), compares against the running version, and caches
the result in Redis with a 24-hour TTL.
"""

import json
import logging
import re
from datetime import UTC, datetime

import httpx
from packaging.version import Version

from app.config import get_app_version
from app.services.app_settings import get_app_settings_service
from app.services.redis_client import get_resilient_redis

logger = logging.getLogger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/seethroughlab/familiar/releases"
REDIS_KEY = "familiar:update_check:result"
REDIS_TTL = 60 * 60 * 24  # 24 hours
HTTPX_TIMEOUT = 10.0


def _normalize_tag(tag: str) -> str:
    """Normalize a GitHub release tag to PEP 440 format.

    Examples:
        v1.0.0          -> 1.0.0
        v1.0.0-alpha.1  -> 1.0.0a1
        v1.0.0-beta.2   -> 1.0.0b2
    """
    v = tag.lstrip("v")
    # Convert -alpha.N / -beta.N to PEP 440 prerelease suffixes
    v = re.sub(r"-alpha\.(\d+)", r"a\1", v)
    v = re.sub(r"-beta\.(\d+)", r"b\1", v)
    return v


def _matches_channel(version: Version, channel: str) -> bool:
    """Check if a version matches the user's selected channel.

    stable: only final releases (no pre-release segments)
    beta:   stable + beta pre-releases
    alpha:  all releases
    """
    if channel == "alpha":
        return True
    if channel == "beta":
        # Accept stable + beta (reject alpha)
        if version.is_prerelease and version.pre is not None:
            return version.pre[0] in ("b", "rc")
        return True
    # stable: no pre-release at all
    return not version.is_prerelease


async def check_for_updates() -> dict:
    """Fetch GitHub releases, compare versions, cache result in Redis.

    Returns the update status dict (also cached in Redis).
    """
    current_version_str = get_app_version()
    settings = get_app_settings_service().get()
    channel = settings.update_channel

    # Skip check when running dev or disabled
    if current_version_str == "dev" or channel == "disabled":
        result = {
            "update_available": False,
            "current_version": current_version_str,
            "latest_version": None,
            "release_url": None,
            "release_name": None,
            "published_at": None,
            "channel": channel,
            "checked_at": datetime.now(tz=UTC).isoformat(),
        }
        _cache_result(result)
        return result

    try:
        current = Version(_normalize_tag(current_version_str))
    except Exception:
        logger.warning(f"Cannot parse current version '{current_version_str}', skipping update check")
        return _error_result(current_version_str, channel, "Cannot parse current version")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            releases = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch GitHub releases: {e}")
        return _error_result(current_version_str, channel, str(e))

    # Find the latest release matching the channel
    best: dict | None = None
    best_version: Version | None = None

    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft"):
            continue
        try:
            v = Version(_normalize_tag(tag))
        except Exception:
            continue
        if not _matches_channel(v, channel):
            continue
        if best_version is None or v > best_version:
            best_version = v
            best = release

    update_available = best_version is not None and best_version > current
    result = {
        "update_available": update_available,
        "current_version": current_version_str,
        "latest_version": str(best_version) if best_version else None,
        "release_url": best["html_url"] if best else None,
        "release_name": best.get("name") if best else None,
        "published_at": best.get("published_at") if best else None,
        "channel": channel,
        "checked_at": datetime.now(tz=UTC).isoformat(),
    }

    _cache_result(result)
    logger.info(
        f"Update check complete: current={current_version_str}, "
        f"latest={best_version}, available={update_available}, channel={channel}"
    )
    return result


def get_cached_result() -> dict | None:
    """Read the cached update check result from Redis."""
    try:
        redis = get_resilient_redis()
        data: bytes | None = redis.get(REDIS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Failed to read cached update result: {e}")
    return None


def _cache_result(result: dict) -> None:
    """Write update check result to Redis with TTL."""
    try:
        redis = get_resilient_redis()
        redis.setex(REDIS_KEY, REDIS_TTL, json.dumps(result))
    except Exception as e:
        logger.warning(f"Failed to cache update result: {e}")


def _error_result(current_version: str, channel: str, error: str) -> dict:
    """Build an error result dict."""
    result = {
        "update_available": False,
        "current_version": current_version,
        "latest_version": None,
        "release_url": None,
        "release_name": None,
        "published_at": None,
        "channel": channel,
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "error": error,
    }
    _cache_result(result)
    return result
