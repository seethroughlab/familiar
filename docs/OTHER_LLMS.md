# Plan: Add Google Gemini LLM Support

## Summary

Add native Google Gemini as a third `LLMProvider` alongside the existing Anthropic and OpenAI-compatible providers.

> **Why "native" when OpenAI-compat already exists?** Google exposes a partial OpenAI-compatible endpoint, but features like grounded function calling, system instructions, and streaming behave differently from the official Gemini SDK. A native provider gives Gemini users full feature parity instead of the lowest-common-denominator slice.

## Difficulty: MODERATE

| Component | Lines of Code | Time Estimate |
|-----------|---------------|---------------|
| `providers_gemini.py` | ~250-350 | 3-4 hours |
| Settings + UI toggle | ~80 | 1 hour |
| Testing | - | 2 hours |
| **Total** | ~330-430 | **6-7 hours** |

## Why It's Feasible

The provider abstraction in `backend/app/services/llm/providers.py` already standardizes everything Gemini needs to plug into:

- `LLMProvider` protocol (`providers.py:28`) — defines `name`, `is_configured()`, `chat()`, `complete_utility()`. Implement these on a `GeminiProvider` class and the service layer Just Works.
- Tool definitions are canonical Anthropic `input_schema` shape — translated per-provider at call time.
- `ToolExecutor` is provider-agnostic.
- Provider selection is already a runtime choice in `get_provider()` (`providers.py:66`) with deferred imports — Gemini's SDK only loads when selected.
- `providers_anthropic.py` and `providers_openai.py` are direct templates for the new file.

## Current Architecture

```
get_provider()          providers.py:66
    ├─ name == "anthropic" → AnthropicProvider   (providers_anthropic.py)
    ├─ name == "openai"    → OpenAIProvider      (providers_openai.py)
    └─ name == "gemini"    → GeminiProvider      [NEW: providers_gemini.py]
                                  ↓
                          ToolExecutor.execute()  ← provider-agnostic
```

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/services/llm/providers_gemini.py` | **New.** `GeminiProvider` class implementing `LLMProvider` protocol |
| `backend/app/services/llm/providers.py` | Add `name == "gemini"` branch in `get_provider()` |
| `backend/app/services/app_settings.py` | Add `gemini_api_key`, `gemini_model`; extend the active-provider enum |
| `backend/app/api/routes/settings.py` | Expose Gemini config + status |
| `packages/frontend/src/components/Settings/` (AI section) | Add "Gemini" radio option + key input |
| `backend/pyproject.toml` | Add `google-generativeai` dependency |
| `backend/tests/llm/` | New tests; mirror existing OpenAI provider test pattern |

## Implementation Steps

### 1. Add Python Dependency

`backend/pyproject.toml`:

```toml
google-generativeai = "^0.8"
```

### 2. Update AppSettings

```python
gemini_api_key: str | None = None
gemini_model: str = "gemini-1.5-pro"
gemini_utility_model: str = "gemini-1.5-flash"
# active_provider: "anthropic" | "openai" | "gemini"
```

### 3. Create `providers_gemini.py`

Mirror the structure of `providers_openai.py`:

```python
class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        settings = get_app_settings_service()
        self.api_key = settings.get_gemini_api_key()
        self.chat_model = settings.get_gemini_model()
        self.utility_model = settings.get_gemini_utility_model()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def chat(self, *, user_message, conversation_history, system_prompt,
                   tools, tool_executor, max_iterations=8):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)

        model = genai.GenerativeModel(
            self.chat_model,
            system_instruction=system_prompt,
            tools=_tools_to_gemini(tools),
        )
        chat = model.start_chat(history=_history_to_gemini(conversation_history))

        response = await chat.send_message_async(user_message)
        for _ in range(max_iterations):
            # walk response.candidates[0].content.parts:
            #   - text part  -> yield {"type": "text", "content": part.text}
            #   - function_call part -> yield {"type": "tool_call", ...}
            #     run tool_executor.execute(name, args)
            #     yield {"type": "tool_result", ...}
            #     send back via chat.send_message_async(FunctionResponse(...))
            # if no function calls remain, break
            ...

    async def complete_utility(self, *, prompt, max_tokens=200, timeout_seconds=30.0):
        ...
```

### 4. Wire Into `get_provider()`

In `providers.py:66-80`:

```python
if name == "gemini":
    from .providers_gemini import GeminiProvider
    return GeminiProvider()
```

### 5. Settings UI

Add a "Gemini" option to the existing provider radio toggle in `packages/frontend/src/components/Settings/` (AI section), and a Gemini API key row in the API Keys panel — alongside the existing Anthropic and OpenAI rows.

### 6. Diagnostics

Mirror what the OpenAI provider exposes: `has_gemini_config`, and ensure `active_provider_configured` honors the Gemini case.

## Tool Format Translation

| Provider | Tool format | Translation function |
|----------|-------------|----------------------|
| Anthropic | Native `input_schema` | None (canonical) |
| OpenAI | OpenAI function-calling | already in `providers_openai.py` |
| Gemini | `FunctionDeclaration` + `Tool` | New helper in `providers_gemini.py` |

```python
def _tools_to_gemini(tools: list[dict]) -> list:
    from google.generativeai.types import FunctionDeclaration, Tool
    return [Tool(function_declarations=[
        FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=tool["input_schema"],
        ) for tool in tools
    ])]
```

## Key Differences From Existing Providers

| Aspect | Anthropic | OpenAI | Gemini |
|--------|-----------|--------|--------|
| SDK | `anthropic` | `openai` | `google-generativeai` |
| System prompt | Top-level param | First message | `system_instruction` on model |
| Tool format | `input_schema` | `function` schema | `FunctionDeclaration` |
| Multi-turn tools | `tool_use` / `tool_result` blocks | `tool_calls` / `tool` role | `FunctionCall` / `FunctionResponse` parts |
| Stop signal | `stop_reason == "end_turn"` | `finish_reason == "stop"` | last response has no function-call parts |
| Streaming | SSE native | SSE native | `send_message_async` returns full response; streaming uses `stream=True` |

## Testing

- Unit-test `GeminiProvider.chat()` with the SDK mocked, mirroring the existing OpenAI provider tests in `backend/tests/`.
- `is_configured()` returns false without `gemini_api_key`.
- `_tools_to_gemini()` round-trips one canonical tool definition.
- Provider selection: `get_provider()` returns `GeminiProvider` when settings select `"gemini"`.

## Notes

- Paid API (like Anthropic; unlike Ollama).
- Worth offering separate `gemini_model` and `gemini_utility_model` so users can pick `gemini-1.5-pro` for chat and `gemini-1.5-flash` for cheap utility calls — same split the OpenAI provider already uses.
- Gemini's SDK is sync-first; use `asyncio.to_thread` if needed for blocking calls.
- Rate-limit handling: surface `google.api_core.exceptions.ResourceExhausted` through `exception_sanitizer` (already recognizes `anthropic.*Error` / `openai.*Error`; add `google.api_core.exceptions.*` to the same path).
