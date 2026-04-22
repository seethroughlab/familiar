"""Tests for Anthropic model unification and literal-model guardrails."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.library_discover import get_curated_prompts
from app.services.llm.models import get_anthropic_model


def _fake_execute_result(rows: list[object]) -> MagicMock:
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


class TestAnthropicModelSelection:
    def test_shared_helper_returns_expected_model_for_all_roles(self) -> None:
        expected = "claude-sonnet-4-5-20250929"
        assert get_anthropic_model("chat") == expected
        assert get_anthropic_model("utility") == expected

    def test_no_direct_claude_model_literals_outside_helper(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app"
        helper_path = root / "services" / "llm" / "models.py"
        forbidden = (
            'model="claude-',
            "model='claude-",
            'model = "claude-',
            "model = 'claude-",
        )

        offenders: list[str] = []
        for path in root.rglob("*.py"):
            if path == helper_path:
                continue
            text = path.read_text()
            if any(token in text for token in forbidden):
                offenders.append(str(path))

        assert offenders == []


@pytest.mark.asyncio
async def test_curated_prompts_routes_through_provider_utility() -> None:
    """Curated prompts should route through the active provider's utility call."""
    db = AsyncMock()
    db.execute.side_effect = [
        _fake_execute_result([SimpleNamespace(genre="Ambient"), SimpleNamespace(genre="Electronic")]),
        _fake_execute_result([SimpleNamespace(artist="Boards of Canada"), SimpleNamespace(artist="Autechre")]),
    ]
    db.scalar.side_effect = [2400, 48]

    with patch("app.api.routes.library_discover.get_redis") as mock_redis:
        cache = MagicMock()
        cache.get.return_value = None
        mock_redis.return_value = cache

        with patch("app.api.routes.library_discover.get_app_settings_service") as mock_settings:
            settings = MagicMock()
            settings.is_active_provider_configured.return_value = True
            mock_settings.return_value = settings

            with patch("app.api.routes.library_discover.get_provider") as mock_get_provider:
                mock_provider = MagicMock()
                mock_provider.complete_utility = AsyncMock(
                    return_value=(
                        '[{"prompt":"Help me rediscover my library.",'
                        '"context":"A familiar way back in.","icon":"music"}]'
                    )
                )
                mock_get_provider.return_value = mock_provider

                response = await get_curated_prompts(
                    db=db,
                    profile=SimpleNamespace(id="profile-123"),
                    refresh=True,
                )

    assert response.prompts[0].prompt == "Help me rediscover my library."
    mock_provider.complete_utility.assert_called_once()
    assert mock_provider.complete_utility.call_args.kwargs["max_tokens"] == 600
