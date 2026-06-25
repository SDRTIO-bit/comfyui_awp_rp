"""Card tools — query imported character cards."""

from __future__ import annotations

import json
from typing import Any

from ...card.import_card import CardImporter
from ..registry import ToolRegistry, ToolDefinition


def _card_get(args: dict[str, Any]) -> str:
    """Get character card details by ID."""
    card_id = args.get("card_id", "")
    if not card_id:
        return "Error: card_id is required"

    importer = CardImporter()
    card = importer.get_card(card_id)
    if not card:
        return f"Error: card '{card_id}' not found"

    manifest = card.get("manifest", {})
    return json.dumps({
        "card_id": card["card_id"],
        "name": manifest.get("name", card_id),
        "description": manifest.get("description", ""),
        "worldbook_entry_count": manifest.get("worldbook_entry_count", 0),
        "greetings": card.get("greetings", []),
        "worldbook_count": len(card.get("worldbook", [])),
    }, ensure_ascii=False, indent=2)


def _card_list(args: dict[str, Any]) -> str:
    """List all imported character cards."""
    importer = CardImporter()
    cards = importer.list_cards()
    return json.dumps([
        {
            "card_id": c["card_id"],
            "name": c["manifest"].get("name", c["card_id"]),
        }
        for c in cards
    ], ensure_ascii=False, indent=2)


def _card_worldbook(args: dict[str, Any]) -> str:
    """Get worldbook entries from a character card."""
    card_id = args.get("card_id", "")
    if not card_id:
        return "Error: card_id is required"

    importer = CardImporter()
    card = importer.get_card(card_id)
    if not card:
        return f"Error: card '{card_id}' not found"

    worldbook = card.get("worldbook", [])
    return json.dumps(worldbook, ensure_ascii=False, indent=2)


def register_card_tools(registry: ToolRegistry) -> None:
    """Register card tools."""
    registry.register(ToolDefinition(
        name="card_get",
        description="Get character card details by ID, including name, description, greetings, and worldbook entry count.",
        parameters={
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "The character card ID."},
            },
            "required": ["card_id"],
        },
        execute_fn=_card_get,
        required_permissions=["card:read"],
        category="card",
    ))

    registry.register(ToolDefinition(
        name="card_list",
        description="List all imported character cards with their IDs and names.",
        parameters={
            "type": "object",
            "properties": {},
        },
        execute_fn=_card_list,
        required_permissions=["card:read"],
        category="card",
    ))

    registry.register(ToolDefinition(
        name="card_worldbook",
        description="Get all worldbook entries from a character card. Use this to find lore, setting facts, and character details from the card.",
        parameters={
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "The character card ID."},
            },
            "required": ["card_id"],
        },
        execute_fn=_card_worldbook,
        required_permissions=["card:read"],
        category="card",
    ))
