"""Tests for provider selection + configuration helpers.

Covers the two correctness traps from the plan:

- Trap 1: A non-null default for `llm_provider` in AppSettings would beat
  env-var precedence. Regression test: with settings.json unset but
  `LLM_PROVIDER=openai` in the environment, `get_active_provider()` must
  return "openai".
- Trap 2: Readiness must gate on the *selected* provider, not "any key set".
"""

from pathlib import Path

import pytest

from app.services.app_settings import AppSettings, AppSettingsService
from app.services.llm.providers import get_provider
from app.services.llm.providers_anthropic import AnthropicProvider
from app.services.llm.providers_openai import OpenAIProvider


@pytest.fixture
def fresh_settings_service(tmp_path: Path, monkeypatch):
    """An AppSettingsService pointing at a fresh empty settings.json.

    Also patches the module-level singleton so callers of
    get_app_settings_service() in producer code see this service.
    """
    service = AppSettingsService(settings_path=tmp_path / "settings.json")
    monkeypatch.setattr(
        "app.services.app_settings._app_settings_service", service
    )
    return service


def _set_env(monkeypatch, **vars):
    """Rebuild app.config.settings with given env-var overrides."""
    from app.config import Settings

    for key, val in vars.items():
        if val is None:
            monkeypatch.delenv(key.upper(), raising=False)
        else:
            monkeypatch.setenv(key.upper(), val)
    monkeypatch.setattr("app.config.settings", Settings())


class TestLLmProviderPrecedence:
    """Trap 1 coverage."""

    def test_defaults_to_anthropic_when_nothing_set(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(monkeypatch, llm_provider=None)
        assert fresh_settings_service.get_active_provider() == "anthropic"

    def test_env_var_wins_when_settings_json_unset(
        self, fresh_settings_service, monkeypatch
    ):
        # settings.json default is None (nullable). Env sets openai.
        _set_env(monkeypatch, llm_provider="openai")
        assert fresh_settings_service.get_active_provider() == "openai"

    def test_settings_json_overrides_env(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(monkeypatch, llm_provider="openai")
        fresh_settings_service.update(llm_provider="anthropic")
        assert fresh_settings_service.get_active_provider() == "anthropic"


class TestActiveProviderConfigured:
    """Trap 2 coverage."""

    def test_anthropic_selected_anthropic_key_present_configured(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(monkeypatch, anthropic_api_key="sk-ant-xxx")
        assert fresh_settings_service.is_active_provider_configured()

    def test_openai_selected_only_anthropic_key_not_configured(
        self, fresh_settings_service, monkeypatch
    ):
        """Trap 2 regression: selecting openai but only anthropic is set."""
        _set_env(
            monkeypatch,
            llm_provider="openai",
            anthropic_api_key="sk-ant-xxx",
            openai_api_key=None,
        )
        assert fresh_settings_service.get_active_provider() == "openai"
        assert not fresh_settings_service.is_active_provider_configured()
        assert not fresh_settings_service.has_openai_config()

    def test_openai_selected_fully_configured(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(
            monkeypatch,
            llm_provider="openai",
            openai_api_key="sk-oa-xxx",
            openai_chat_model="gpt-4o",
            openai_utility_model="gpt-4o-mini",
        )
        assert fresh_settings_service.has_openai_config()
        assert fresh_settings_service.is_active_provider_configured()

    def test_openai_selected_missing_model_not_configured(
        self, fresh_settings_service, monkeypatch
    ):
        """base_url is optional, but chat + utility model names are required."""
        _set_env(
            monkeypatch,
            llm_provider="openai",
            openai_api_key="sk-oa-xxx",
            # chat model missing
            openai_utility_model="gpt-4o-mini",
        )
        assert not fresh_settings_service.has_openai_config()


class TestGetProviderFactory:
    def test_returns_anthropic_by_default(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(monkeypatch, llm_provider=None)
        assert isinstance(get_provider(), AnthropicProvider)

    def test_returns_openai_when_selected_via_env(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(monkeypatch, llm_provider="openai")
        assert isinstance(get_provider(), OpenAIProvider)

    def test_returns_openai_when_selected_via_settings(
        self, fresh_settings_service, monkeypatch
    ):
        _set_env(monkeypatch)
        fresh_settings_service.update(llm_provider="openai")
        assert isinstance(get_provider(), OpenAIProvider)


def test_appsettings_llm_provider_defaults_to_none():
    """Structural Trap 1 check: a truthy default would silently break env fallback."""
    assert AppSettings().llm_provider is None
