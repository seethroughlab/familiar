"""Tests for plugin service - URL parsing, manifest validation."""

import pytest

from app.services.plugins import (
    CURRENT_API_VERSION,
    PluginInstallResult,
    PluginManifest,
    PluginUpdateCheck,
    parse_github_url,
)


class TestParseGithubUrl:
    def test_basic_repo_url(self):
        user, repo, ref = parse_github_url("https://github.com/user/repo")
        assert user == "user"
        assert repo == "repo"
        assert ref == "main"

    def test_with_trailing_slash(self):
        user, repo, ref = parse_github_url("https://github.com/user/repo/")
        assert user == "user"
        assert repo == "repo"

    def test_branch_url(self):
        user, repo, ref = parse_github_url("https://github.com/user/repo/tree/develop")
        assert user == "user"
        assert repo == "repo"
        assert ref == "develop"

    def test_release_tag_url(self):
        user, repo, ref = parse_github_url("https://github.com/user/repo/releases/tag/v1.0.0")
        assert user == "user"
        assert repo == "repo"
        assert ref == "v1.0.0"

    def test_http_url(self):
        user, repo, ref = parse_github_url("http://github.com/user/repo")
        assert user == "user"
        assert repo == "repo"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            parse_github_url("https://gitlab.com/user/repo")

    def test_non_github_raises(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            parse_github_url("not-a-url")


class TestPluginManifest:
    def test_valid_manifest(self):
        m = PluginManifest(
            name="Test Visualizer",
            id="test-viz",
            version="1.0.0",
            type="visualizer",
        )
        assert m.name == "Test Visualizer"
        assert m.id == "test-viz"

    def test_invalid_id_pattern(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PluginManifest(
                name="Bad",
                id="UPPER_CASE",  # Must be lowercase alphanumeric with hyphens
                version="1.0.0",
                type="visualizer",
            )

    def test_default_main(self):
        m = PluginManifest(
            name="Test",
            id="test",
            version="1.0.0",
            type="visualizer",
        )
        assert m.main == "dist/index.js"

    def test_with_author(self):
        m = PluginManifest(
            name="Test",
            id="test",
            version="1.0.0",
            type="browser",
            author={"name": "Author", "url": "https://example.com"},
        )
        assert m.author["name"] == "Author"


class TestPluginInstallResult:
    def test_success(self):
        r = PluginInstallResult(success=True, plugin_id="test-viz")
        assert r.success is True
        assert r.error is None

    def test_failure(self):
        r = PluginInstallResult(success=False, error="Download failed")
        assert r.success is False
        assert r.error == "Download failed"


class TestPluginUpdateCheck:
    def test_no_update(self):
        r = PluginUpdateCheck(has_update=False, current_version="1.0.0")
        assert r.has_update is False

    def test_has_update(self):
        r = PluginUpdateCheck(
            has_update=True,
            current_version="1.0.0",
            latest_version="2.0.0",
        )
        assert r.has_update is True
        assert r.latest_version == "2.0.0"


class TestApiVersion:
    def test_current_version(self):
        assert CURRENT_API_VERSION >= 1
