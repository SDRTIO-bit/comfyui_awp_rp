"""Built-in tools for the AWP RP agent system.

These wrap existing memory, worldbook, retrieval, and card functionality
into callable tools that an agent can invoke during an agent loop.
"""

from __future__ import annotations

from ..registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools into the given registry."""
    from .memory_tools import register_memory_tools
    from .worldbook_tools import register_worldbook_tools
    from .retrieval_tools import register_retrieval_tools
    from .card_tools import register_card_tools
    from .continuity_tools import register_continuity_tools
    from .delegate_tool import register_delegate_tool
    from .npc_tools import register_npc_tools
    from .story_plan_tool import register_story_plan_tools
    from .injection_tool import register_injection_tools

    register_memory_tools(registry)
    register_worldbook_tools(registry)
    register_retrieval_tools(registry)
    register_card_tools(registry)
    register_continuity_tools(registry)
    register_delegate_tool(registry)
    register_npc_tools(registry)
    register_story_plan_tools(registry)
    register_injection_tools(registry)
