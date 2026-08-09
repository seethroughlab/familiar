"""Anthropic model unification and the literal-model guardrail.

The curated-prompts test that lived here went with `GET /library/discover/prompts` in ADR-0048
step 3 — it asserted that endpoint routed through `complete_utility`, and neither exists now.
What remains is `models.py` itself, which step 4 removes along with the rest of the provider layer.
"""

from pathlib import Path

from app.services.llm.models import get_anthropic_model


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
