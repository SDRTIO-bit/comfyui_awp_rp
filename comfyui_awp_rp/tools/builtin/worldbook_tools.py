"""Worldbook tools — search and manage worldbook entries."""

from __future__ import annotations

import json
from typing import Any

from ...knowledge.worldbook import WorldbookManager
from ..registry import ToolRegistry, ToolDefinition


def _worldbook_search(args: dict[str, Any]) -> str:
    """Search worldbook entries."""
    session_id = args.get("session_id", "default")
    resource_ref = args.get("resource_ref", "main")
    tags_any = args.get("tags_any", [])
    limit = args.get("limit", 20)

    manager = WorldbookManager()
    worldbook = manager.get_worldbook(session_id, resource_ref)
    entries = worldbook.query(
        tags_any=tags_any if tags_any else None,
        limit=limit,
    )
    return json.dumps([
        {
            "id": e.id,
            "title": e.title,
            "content": e.content,
            "tags": e.tags,
            "priority": e.priority,
        }
        for e in entries
    ], ensure_ascii=False, indent=2)


def _worldbook_add(args: dict[str, Any]) -> str:
    """Add a worldbook entry."""
    session_id = args.get("session_id", "default")
    resource_ref = args.get("resource_ref", "main")
    content = args.get("content", "")
    title = args.get("title", "")
    tags = args.get("tags", [])

    if not content:
        return "Error: content is required"

    manager = WorldbookManager()
    worldbook = manager.get_worldbook(session_id, resource_ref)
    entry = worldbook.add_entry(
        content=content,
        title=title if title else None,
        tags=tags if tags else None,
    )
    return f"Added worldbook entry: {entry.id}"


def _worldbook_update(args: dict[str, Any]) -> str:
    """Update a worldbook entry."""
    session_id = args.get("session_id", "default")
    resource_ref = args.get("resource_ref", "main")
    entry_id = args.get("entry_id", "")
    content = args.get("content", "")
    title = args.get("title", "")
    tags = args.get("tags", [])

    if not entry_id:
        return "Error: entry_id is required"

    manager = WorldbookManager()
    worldbook = manager.get_worldbook(session_id, resource_ref)
    entry = worldbook.update_entry(
        entry_id=entry_id,
        content=content if content else None,
        title=title if title else None,
        tags=tags if tags else None,
    )
    if entry:
        return f"Updated worldbook entry: {entry.id}"
    return "Error: entry not found"


def _worldbook_delete(args: dict[str, Any]) -> str:
    """Delete a worldbook entry."""
    session_id = args.get("session_id", "default")
    resource_ref = args.get("resource_ref", "main")
    entry_id = args.get("entry_id", "")

    if not entry_id:
        return "Error: entry_id is required"

    manager = WorldbookManager()
    worldbook = manager.get_worldbook(session_id, resource_ref)
    success = worldbook.delete_entry(entry_id)
    return f"Deleted: {success}" if success else "Entry not found"


def register_worldbook_tools(registry: ToolRegistry) -> None:
    """Register worldbook tools."""
    registry.register(ToolDefinition(
        name="worldbook_search",
        description="Search worldbook entries for a session. Use this to find lore, setting facts, character details, and location descriptions.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID."},
                "resource_ref": {"type": "string", "description": "Worldbook resource reference.", "default": "main"},
                "tags_any": {"type": "array", "items": {"type": "string"}, "description": "Optional tags to filter."},
                "limit": {"type": "integer", "description": "Max entries to return.", "default": 20},
            },
            "required": ["session_id"],
        },
        execute_fn=_worldbook_search,
        required_permissions=["worldbook:read"],
        category="knowledge",
    ))

    registry.register(ToolDefinition(
        name="worldbook_add",
        description="Add a new entry to the worldbook. Use this when new world facts, locations, or character details are established during the story.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID."},
                "resource_ref": {"type": "string", "description": "Worldbook resource reference.", "default": "main"},
                "content": {"type": "string", "description": "Entry content."},
                "title": {"type": "string", "description": "Optional entry title."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
            },
            "required": ["session_id", "content"],
        },
        execute_fn=_worldbook_add,
        required_permissions=["worldbook:write"],
        category="knowledge",
    ))

    registry.register(ToolDefinition(
        name="worldbook_update",
        description="Update an existing worldbook entry.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID."},
                "resource_ref": {"type": "string", "description": "Worldbook resource reference.", "default": "main"},
                "entry_id": {"type": "string", "description": "ID of the entry to update."},
                "content": {"type": "string", "description": "New content."},
                "title": {"type": "string", "description": "New title."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags."},
            },
            "required": ["session_id", "entry_id"],
        },
        execute_fn=_worldbook_update,
        required_permissions=["worldbook:write"],
        category="knowledge",
    ))

    registry.register(ToolDefinition(
        name="worldbook_delete",
        description="Delete a worldbook entry.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID."},
                "resource_ref": {"type": "string", "description": "Worldbook resource reference.", "default": "main"},
                "entry_id": {"type": "string", "description": "ID of the entry to delete."},
            },
            "required": ["session_id", "entry_id"],
        },
        execute_fn=_worldbook_delete,
        required_permissions=["worldbook:write"],
        category="knowledge",
    ))
