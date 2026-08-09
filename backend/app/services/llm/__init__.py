"""Tool definitions and execution for Familiar's LLM surface.

**This package no longer runs a conversation.** ADR-0043 replaced Familiar's own chat client with an
MCP server, and ADR-0043 point 5 retired `service.py` — the tool-and-conversation loop — along with
the chat route and both chat UIs. What survives is the part an MCP host needs:

- ``MUSIC_TOOLS``: the tool schemas, iterated by ``app.mcp.server.exposed_tools``
- ``ToolExecutor``: the handlers those schemas dispatch to
- ``SYSTEM_PROMPT``: retained because it is still the best written description of how these tools
  are meant to be used together; ``app/mcp/server.py`` sends its own ``INSTRUCTIONS`` to hosts.

The provider layer (``providers.py``, ``providers_anthropic.py``, ``providers_openai.py``,
``models.py``) is a separate concern and is not imported here — Familiar calls a model itself only
for utility completions, never for chat.
"""

from .executor import ToolExecutor
from .tools import MUSIC_TOOLS, SYSTEM_PROMPT

__all__ = [
    "ToolExecutor",
    "MUSIC_TOOLS",
    "SYSTEM_PROMPT",
]
