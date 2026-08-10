# handlers/ — LLM Tool-Use Handler Mixins

Owns mixin classes that implement Claude tool-use handlers — one mixin per domain.

## Public API (re-exported from `__init__.py`)

- `AnalysisHandlersMixin` — track analysis tools
- `DiscoveryHandlersMixin` — music discovery/recommendation tools
- `LibraryInfoHandlersMixin` — library stats and info tools
- `MetadataHandlersMixin` — metadata lookup/edit tools
- `PlaybackHandlersMixin` — playback control tools
- `PlaylistHandlersMixin` — playlist management tools
- `SearchHandlersMixin` — library search tools

All 7 mixins are composed into `ToolExecutor` (in `llm/executor.py`) via multiple inheritance.

## Does NOT handle

- Tool schema definitions (`llm/tools.py`)
- LLM API communication (`llm/service.py`, `llm/providers.py`)
- Audio processing
- Database schema
