"""Plugin service for managing external visualizers and library browsers.

Handles installation, updates, and management of plugins from GitHub repositories.
Plugins provide pre-built JavaScript bundles that register themselves with the app's
visualizer or browser registry at runtime.
"""

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plugin, PluginType

# Current plugin API version supported by this app
CURRENT_API_VERSION = 1
MIN_SUPPORTED_API_VERSION = 1


class PluginManifest(BaseModel):
    """Schema for familiar-plugin.json manifest files."""

    name: str
    id: str = Field(..., pattern=r"^[a-z0-9-]+$")
    version: str
    type: str  # "visualizer" or "browser"
    description: str | None = None
    author: dict[str, str] | None = None  # {"name": "...", "url": "..."}
    main: str = "dist/index.js"
    familiar: dict[str, Any] | None = None  # {"apiVersion": 1}
    icon: str | None = None
    preview: str | None = None


class PluginInstallResult(BaseModel):
    """Result of a plugin installation attempt."""

    success: bool
    plugin_id: str | None = None
    error: str | None = None


class PluginUpdateCheck(BaseModel):
    """Result of checking for plugin updates."""

    has_update: bool
    current_version: str
    latest_version: str | None = None
    error: str | None = None


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Parse a GitHub URL into (user, repo, ref).

    Supports:
    - https://github.com/user/repo
    - https://github.com/user/repo/tree/branch
    - https://github.com/user/repo/releases/tag/v1.0.0

    Returns:
        Tuple of (user, repo, ref) where ref is branch/tag or "main" as default
    """
    # Remove trailing slash
    url = url.rstrip("/")

    # Pattern for github.com URLs
    patterns = [
        # Standard repo URL
        r"^https?://github\.com/([^/]+)/([^/]+)$",
        # Branch/tag URL
        r"^https?://github\.com/([^/]+)/([^/]+)/tree/(.+)$",
        # Release URL
        r"^https?://github\.com/([^/]+)/([^/]+)/releases/tag/(.+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return groups[0], groups[1], "main"
            else:
                return groups[0], groups[1], groups[2]

    raise ValueError(f"Invalid GitHub URL: {url}")


class PluginService:
    """Service for managing plugins."""

    def __init__(self, plugins_path: Path | None = None):
        self.plugins_path = plugins_path or Path("data/plugins")
        self.plugins_path.mkdir(parents=True, exist_ok=True)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_manifest(self, user: str, repo: str, ref: str) -> PluginManifest:
        """Fetch and validate plugin manifest from GitHub."""
        client = await self._get_client()

        # Try familiar-plugin.json first, then package.json with familiar field
        manifest_url = f"https://raw.githubusercontent.com/{user}/{repo}/{ref}/familiar-plugin.json"

        response = await client.get(manifest_url)
        if response.status_code == 404:
            # Check if the repo itself is accessible to give a better error
            repo_response = await client.get(f"https://api.github.com/repos/{user}/{repo}")
            if repo_response.status_code == 404:
                raise ValueError(
                    f"Repository {user}/{repo} not found. "
                    "It may be private, or the URL may be incorrect."
                )
            # Repo exists, check if the branch exists
            branch_response = await client.get(
                f"https://api.github.com/repos/{user}/{repo}/branches/{ref}"
            )
            if branch_response.status_code == 404:
                raise ValueError(
                    f"Branch '{ref}' not found in {user}/{repo}. "
                    f"Check if the repository uses a different default branch (e.g., 'master' instead of 'main')."
                )
            # Branch exists, so the file must be missing
            raise ValueError(
                f"No familiar-plugin.json found in {user}/{repo} on branch '{ref}'. "
                "Plugin repositories must include a familiar-plugin.json manifest."
            )
        response.raise_for_status()

        try:
            data = response.json()
            return PluginManifest(**data)
        except Exception as e:
            raise ValueError(f"Invalid manifest format: {e}")

    async def fetch_bundle(self, user: str, repo: str, ref: str, main_path: str) -> bytes:
        """Fetch the plugin bundle from GitHub."""
        client = await self._get_client()

        bundle_url = f"https://raw.githubusercontent.com/{user}/{repo}/{ref}/{main_path}"

        response = await client.get(bundle_url)
        if response.status_code == 404:
            raise ValueError(
                f"Bundle not found at {main_path}. "
                "Ensure the plugin has been built and the 'main' path in manifest is correct."
            )
        response.raise_for_status()

        return response.content

    def validate_manifest(self, manifest: PluginManifest) -> None:
        """Validate manifest for compatibility."""
        # Check plugin type
        if manifest.type not in ("visualizer", "browser"):
            raise ValueError(f"Invalid plugin type: {manifest.type}. Must be 'visualizer' or 'browser'.")

        # Check API version
        api_version = 1
        if manifest.familiar and "apiVersion" in manifest.familiar:
            api_version = manifest.familiar["apiVersion"]

        if api_version > CURRENT_API_VERSION:
            raise ValueError(
                f"Plugin requires API version {api_version}, "
                f"but this app only supports up to version {CURRENT_API_VERSION}. "
                "Please update Familiar to use this plugin."
            )

        if api_version < MIN_SUPPORTED_API_VERSION:
            raise ValueError(
                f"Plugin uses deprecated API version {api_version}. "
                f"Minimum supported version is {MIN_SUPPORTED_API_VERSION}. "
                "Please update the plugin."
            )

    async def install(
        self,
        db: AsyncSession,
        github_url: str,
    ) -> PluginInstallResult:
        """Install a plugin from a GitHub URL."""
        try:
            # Parse URL
            user, repo, ref = parse_github_url(github_url)

            # Fetch manifest
            manifest = await self.fetch_manifest(user, repo, ref)

            # Validate
            self.validate_manifest(manifest)

            # Check if already installed
            existing = await db.execute(
                select(Plugin).where(Plugin.plugin_id == manifest.id)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Plugin '{manifest.id}' is already installed.")

            # Fetch bundle
            bundle_content = await self.fetch_bundle(user, repo, ref, manifest.main)
            bundle_hash = hashlib.sha256(bundle_content).hexdigest()

            from app.utils.atomic_write import atomic_write_bytes, atomic_write_text

            # Create local directory
            plugin_dir = self.plugins_path / manifest.id
            plugin_dir.mkdir(parents=True, exist_ok=True)

            # Write bundle and manifest atomically
            bundle_path = plugin_dir / "bundle.js"
            atomic_write_bytes(bundle_path, bundle_content)

            manifest_path = plugin_dir / "manifest.json"
            atomic_write_text(manifest_path, manifest.model_dump_json(indent=2))

            # Create database record
            plugin = Plugin(
                plugin_id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                plugin_type=PluginType(manifest.type),
                description=manifest.description,
                author_name=manifest.author.get("name") if manifest.author else None,
                author_url=manifest.author.get("url") if manifest.author else None,
                repository_url=f"https://github.com/{user}/{repo}",
                installed_from=github_url,
                bundle_path=str(bundle_path.relative_to(self.plugins_path.parent)),
                bundle_hash=bundle_hash,
                api_version=manifest.familiar.get("apiVersion", 1) if manifest.familiar else 1,
                min_familiar_version=manifest.familiar.get("minVersion") if manifest.familiar else None,
                manifest=manifest.model_dump(),
            )
            db.add(plugin)
            try:
                await db.commit()
            except Exception:
                # DB commit failed — remove written files so we don't leave
                # orphaned plugin files with no matching DB record.
                shutil.rmtree(plugin_dir, ignore_errors=True)
                raise

            return PluginInstallResult(success=True, plugin_id=manifest.id)

        except Exception as e:
            return PluginInstallResult(success=False, error=str(e))

    async def uninstall(self, db: AsyncSession, plugin_id: str) -> bool:
        """Uninstall a plugin."""
        result = await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            return False

        # Remove files
        plugin_dir = self.plugins_path / plugin_id
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        # Remove database record
        await db.delete(plugin)
        await db.commit()

        return True

    async def update_plugin(
        self,
        db: AsyncSession,
        plugin_id: str,
    ) -> PluginInstallResult:
        """Update a plugin to the latest version."""
        result = await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            return PluginInstallResult(success=False, error="Plugin not found")

        try:
            # Parse original URL
            user, repo, _ = parse_github_url(plugin.repository_url)

            # Fetch latest manifest (from main/default branch)
            manifest = await self.fetch_manifest(user, repo, "main")
            self.validate_manifest(manifest)

            # Fetch new bundle
            bundle_content = await self.fetch_bundle(user, repo, "main", manifest.main)
            bundle_hash = hashlib.sha256(bundle_content).hexdigest()

            # Check if actually changed
            if bundle_hash == plugin.bundle_hash:
                return PluginInstallResult(success=True, plugin_id=plugin_id)

            from app.utils.atomic_write import atomic_write_bytes, atomic_write_text

            # Update local files atomically
            plugin_dir = self.plugins_path / plugin_id
            bundle_path = plugin_dir / "bundle.js"
            atomic_write_bytes(bundle_path, bundle_content)

            manifest_path = plugin_dir / "manifest.json"
            atomic_write_text(manifest_path, manifest.model_dump_json(indent=2))

            # Update database record
            plugin.version = manifest.version
            plugin.name = manifest.name
            plugin.description = manifest.description
            plugin.author_name = manifest.author.get("name") if manifest.author else None
            plugin.author_url = manifest.author.get("url") if manifest.author else None
            plugin.bundle_hash = bundle_hash
            plugin.api_version = manifest.familiar.get("apiVersion", 1) if manifest.familiar else 1
            plugin.manifest = manifest.model_dump()
            plugin.load_error = None  # Clear any previous errors

            await db.commit()

            return PluginInstallResult(success=True, plugin_id=plugin_id)

        except Exception as e:
            return PluginInstallResult(success=False, error=str(e))

    async def check_for_update(
        self,
        db: AsyncSession,
        plugin_id: str,
    ) -> PluginUpdateCheck:
        """Check if a newer version of a plugin is available."""
        result = await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            return PluginUpdateCheck(
                has_update=False,
                current_version="unknown",
                error="Plugin not found",
            )

        try:
            user, repo, _ = parse_github_url(plugin.repository_url)
            manifest = await self.fetch_manifest(user, repo, "main")

            # Update last check timestamp
            plugin.last_update_check = datetime.utcnow()
            await db.commit()

            # Compare versions (simple string comparison for now)
            # Could use semver for proper comparison
            has_update = manifest.version != plugin.version

            return PluginUpdateCheck(
                has_update=has_update,
                current_version=plugin.version,
                latest_version=manifest.version,
            )

        except Exception as e:
            return PluginUpdateCheck(
                has_update=False,
                current_version=plugin.version,
                error=str(e),
            )

    async def set_enabled(
        self,
        db: AsyncSession,
        plugin_id: str,
        enabled: bool,
    ) -> bool:
        """Enable or disable a plugin."""
        result = await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            return False

        plugin.enabled = enabled
        if enabled:
            plugin.load_error = None  # Clear error when re-enabling
        await db.commit()

        return True

    async def report_load_error(
        self,
        db: AsyncSession,
        plugin_id: str,
        error: str,
    ) -> bool:
        """Record a plugin load error from the frontend."""
        result = await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            return False

        plugin.load_error = error
        await db.commit()

        return True

    async def list_plugins(
        self,
        db: AsyncSession,
        plugin_type: PluginType | None = None,
        enabled_only: bool = False,
    ) -> list[Plugin]:
        """List installed plugins."""
        query = select(Plugin).order_by(Plugin.name)

        if plugin_type:
            query = query.where(Plugin.plugin_type == plugin_type)

        if enabled_only:
            query = query.where(Plugin.enabled.is_(True))

        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_plugin(self, db: AsyncSession, plugin_id: str) -> Plugin | None:
        """Get a specific plugin by ID."""
        result = await db.execute(select(Plugin).where(Plugin.plugin_id == plugin_id))
        return result.scalar_one_or_none()

    def get_bundle_path(self, plugin_id: str) -> Path | None:
        """Get the local path to a plugin's bundle."""
        bundle_path = self.plugins_path / plugin_id / "bundle.js"
        if bundle_path.exists():
            return bundle_path
        return None

    def get_asset_path(self, plugin_id: str, asset_path: str) -> Path | None:
        """Get the local path to a plugin's asset file.

        Args:
            plugin_id: The plugin identifier
            asset_path: Relative path to the asset within the plugin's public/ folder

        Returns:
            Path to the asset file if it exists, None otherwise
        """
        # Normalize path and prevent directory traversal
        clean_path = Path(asset_path).as_posix().lstrip("/")
        if ".." in clean_path:
            return None

        # Look in public/ folder within plugin directory
        full_path = self.plugins_path / plugin_id / "public" / clean_path
        if full_path.exists() and full_path.is_file():
            return full_path
        return None


# Singleton instance
_plugin_service: PluginService | None = None


def get_plugin_service() -> PluginService:
    """Get or create the plugin service singleton."""
    global _plugin_service
    if _plugin_service is None:
        _plugin_service = PluginService()
    return _plugin_service
