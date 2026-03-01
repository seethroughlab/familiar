# Plan: Add OpenAI (ChatGPT) and Google Gemini LLM Support

## Summary

Add support for OpenAI and Google Gemini as alternative LLM providers alongside Claude and Ollama.

## Difficulty: MODERATE

| Provider | Lines of Code | Time Estimate |
|----------|---------------|---------------|
| OpenAI (ChatGPT) | ~200-300 | 2-3 hours |
| Google Gemini | ~250-350 | 3-4 hours |
| Settings/UI | ~100 | 1 hour |
| Testing | - | 2 hours |
| **Total** | ~550-750 | **8-10 hours** |

## Why It's Feasible

- Tool definitions already provider-agnostic (JSON schema in `tools.py`)
- Tool executor completely provider-independent (`executor.py`)
- OpenAI uses same tool format as Ollama (can reuse `convert_tools_to_ollama_format()`)
- Settings system already handles multiple providers

## Current Architecture

```
LLMService.chat()
    ├─ provider == "claude" → _chat_claude()
    ├─ provider == "ollama" → _chat_ollama()
    ├─ provider == "openai" → _chat_openai()  [NEW]
    └─ provider == "gemini" → _chat_gemini()  [NEW]
           ↓
    ToolExecutor.execute() ← Provider-agnostic (no changes needed)
```

## Files to Modify

| File | Changes |
|------|---------|
| `backend/app/services/llm/service.py` | Add `_chat_openai()` and `_chat_gemini()` |
| `backend/app/services/llm/providers.py` | Add `OpenAIClient` and `GeminiClient` |
| `backend/app/services/app_settings.py` | Add `openai_api_key`, `gemini_api_key` |
| `backend/app/api/routes/settings.py` | Expose new API key fields |
| `frontend/src/components/Admin/AdminSetup.tsx` | Add config UI sections |
| `backend/pyproject.toml` | Add `openai`, `google-generativeai` deps |

## Implementation Steps

### 1. Add Python Dependencies
```toml
openai = "^1.0"
google-generativeai = "^0.3"
```

### 2. Update AppSettings
```python
openai_api_key: str | None = None
openai_model: str = "gpt-4o"
gemini_api_key: str | None = None
gemini_model: str = "gemini-1.5-pro"
# llm_provider: "claude" | "ollama" | "openai" | "gemini"
```

### 3. Add OpenAI Client (`providers.py`)
```python
class OpenAIClient:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def chat(self, messages, system, tools):
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}] + messages,
            tools=tools,  # Same format as Ollama
        )
        return response
```

### 4. Add Gemini Client (`providers.py`)
```python
class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    async def chat(self, messages, system, tools):
        # Convert messages to Gemini format
        # Convert tools to Gemini function declarations
        # Handle response and tool calls
```

### 5. Add Chat Methods (`service.py`)

#### OpenAI Method
```python
async def _chat_openai(self, message, history, db, profile_id):
    """Chat using OpenAI API."""
    tool_executor = ToolExecutor(db, profile_id)
    messages = self._build_openai_messages(history, message)

    for _ in range(10):  # Max iterations
        response = await self.openai_client.chat(
            messages=messages,
            system=SYSTEM_PROMPT,
            tools=convert_tools_to_ollama_format(MUSIC_TOOLS),
        )

        choice = response.choices[0]

        # Handle tool calls
        if choice.message.tool_calls:
            for tool_call in choice.message.tool_calls:
                result = await tool_executor.execute(
                    tool_call.function.name,
                    json.loads(tool_call.function.arguments)
                )
                yield {"type": "tool_result", ...}
                messages.append({"role": "tool", "content": json.dumps(result), ...})

        # Handle text response
        if choice.message.content:
            yield {"type": "text", "content": choice.message.content}

        if choice.finish_reason == "stop":
            break

    yield {"type": "done"}
```

#### Gemini Method
```python
async def _chat_gemini(self, message, history, db, profile_id):
    """Chat using Google Gemini API."""
    # Similar structure but with Gemini-specific:
    # - Message format conversion
    # - Tool declaration format
    # - Response parsing
```

### 6. Update Provider Routing
```python
async def chat(self, message, history, db, profile_id):
    if self.provider == "openai":
        async for event in self._chat_openai(message, history, db, profile_id):
            yield event
    elif self.provider == "gemini":
        async for event in self._chat_gemini(message, history, db, profile_id):
            yield event
    elif self.provider == "ollama":
        async for event in self._chat_ollama(message, history, db, profile_id):
            yield event
    else:  # claude (default)
        async for event in self._chat_claude(message, history, db, profile_id):
            yield event
```

### 7. Update Admin UI

Add new sections to `AdminSetup.tsx`:

```tsx
{/* OpenAI API Section */}
<div className="bg-zinc-900 rounded-xl p-6">
  <div className="flex items-center gap-3 mb-4">
    <Bot className="w-5 h-5 text-green-400" />
    <h2>OpenAI API</h2>
  </div>
  <input
    type="password"
    placeholder="sk-..."
    value={openaiKey}
    onChange={(e) => setOpenaiKey(e.target.value)}
  />
  <button onClick={saveOpenai}>Save</button>
</div>

{/* Google Gemini Section */}
<div className="bg-zinc-900 rounded-xl p-6">
  <div className="flex items-center gap-3 mb-4">
    <Sparkles className="w-5 h-5 text-blue-400" />
    <h2>Google Gemini API</h2>
  </div>
  <input
    type="password"
    placeholder="AI..."
    value={geminiKey}
    onChange={(e) => setGeminiKey(e.target.value)}
  />
  <button onClick={saveGemini}>Save</button>
</div>
```

Update AI Provider selector to include new options:
```tsx
<button onClick={() => setLlmProvider('openai')}>OpenAI</button>
<button onClick={() => setLlmProvider('gemini')}>Gemini</button>
```

## Tool Format Compatibility

| Provider | Tool Format | Conversion |
|----------|-------------|------------|
| Claude | Anthropic native | None (source format) |
| Ollama | OpenAI-compatible | `convert_tools_to_ollama_format()` |
| OpenAI | OpenAI native | Reuse Ollama conversion |
| Gemini | Google format | New `convert_tools_to_gemini_format()` |

### Gemini Tool Format
```python
def convert_tools_to_gemini_format(tools):
    """Convert tools to Gemini function declarations."""
    from google.generativeai.types import FunctionDeclaration

    declarations = []
    for tool in tools:
        declarations.append(FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=tool["input_schema"],
        ))
    return declarations
```

## Key Differences Between Providers

| Aspect | Claude | OpenAI | Gemini |
|--------|--------|--------|--------|
| SDK | `anthropic` | `openai` | `google-generativeai` |
| Tool format | Native | OpenAI format | Google format |
| Stop signal | `stop_reason == "end_turn"` | `finish_reason == "stop"` | `finish_reason` |
| Streaming | SSE native | SSE native | Different format |
| System prompt | Separate param | First message | `system_instruction` |

## Notes

- **OpenAI** is straightforward - uses same tool format as Ollama
- **Gemini** requires more work - different message format and tool declarations
- Both are **paid APIs** (like Claude, unlike Ollama which is free/local)
- Consider adding **model selection dropdowns** in UI (gpt-4o vs gpt-4-turbo, gemini-1.5-pro vs flash)
- May need to handle **rate limiting** differently per provider
