"""Card structure detection — analyze character card for phase personas and events.

Port of oh-story-claudecode's card structure detection from import_prepare.py.
Analyzes imported card data to detect:
- Phase-based personas (character changes at different story stages)
- Event libraries (triggered events at specific phases)
- Variable structure (from tavern_helper Zod schema)

This information guides the agent to follow the card author's intended
narrative structure rather than improvising character arcs.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def detect_card_structure(card_data: dict[str, Any]) -> dict[str, Any]:
    """Analyze a character card and extract structural metadata.

    Args:
        card_data: Raw card data dict (from .card_data.json or import result).

    Returns:
        Structured analysis result with phases, events, and variable info.
    """
    result: dict[str, Any] = {
        "has_structure": False,
        "phases": [],
        "events": [],
        "variables": {},
        "phase_triggers": [],
    }

    data = card_data.get("data", card_data)
    if not isinstance(data, dict):
        return result

    # ── Detect phase personas from description ──
    description = data.get("description", "") or data.get("personality", "")
    phases = _extract_phases(description)
    if phases:
        result["phases"] = phases
        result["has_structure"] = True

    # ── Detect event library from extensions ──
    extensions = data.get("extensions", {})
    if isinstance(extensions, dict):
        # Check tavern_helper for MVU schema (indicates structured card)
        tavern = extensions.get("tavern_helper", {})
        if isinstance(tavern, dict):
            scripts = tavern.get("scripts", [])
            if scripts:
                result["has_structure"] = True
                result["variables"]["has_mvu_schema"] = True
                # Extract variable paths from script analysis
                var_paths = _extract_variable_paths(scripts)
                if var_paths:
                    result["variables"]["paths"] = var_paths

            # Check for phase/event definitions in worldbook entries
            worldbook = extensions.get("worldbook", {})
            if isinstance(worldbook, dict):
                entries = worldbook.get("entries", [])
                events = _extract_events(entries)
                if events:
                    result["events"] = events
                    result["has_structure"] = True

    # ── Detect phase triggers from worldbook keywords ──
    triggers = _extract_phase_triggers(phases)
    if triggers:
        result["phase_triggers"] = triggers

    return result


def _extract_phases(text: str) -> list[dict[str, str]]:
    """Extract phase-based persona definitions from description text.

    Looks for patterns like:
    - "阶段1: ..." / "Phase 1: ..."
    - "初期: ..." / "后期: ..."
    - "[Phase1]" / "[阶段一]"
    """
    import re

    phases: list[dict[str, str]] = []
    phase_patterns = [
        r'(?:阶段|Phase)\s*(\d+|[一二三四五六七八九十]+)\s*[:：]\s*(.+?)(?=(?:阶段|Phase)\s*\d+|$)',
        r'\[(?:阶段|Phase)\s*(\d+|[一二三四五六七八九十]+)\]\s*(.+?)(?=\[|$)',
        r'(初期|中期|后期|末期)\s*[:：]\s*(.+?)(?=(?:初期|中期|后期|末期)|$)',
    ]

    for pattern in phase_patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            phase_num = match.group(1).strip()
            phase_desc = match.group(2).strip()[:300]
            phases.append({
                "phase": phase_num,
                "description": phase_desc,
            })

    return phases


def _extract_events(entries: list[dict]) -> list[dict[str, Any]]:
    """Extract event library from worldbook entries.

    Events are worldbook entries whose keywords contain event-like patterns:
    - "事件_" / "event_"
    - "触发_" / "trigger_"
    - Entries with "stage" or "phase" in their keywords
    """
    events: list[dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", entry.get("keyword", "")))
        if any(trigger in key.lower() for trigger in
               ("事件", "event", "触发", "trigger", "stage", "phase", "阶段", "条件")):
            events.append({
                "key": key,
                "content": str(entry.get("content", ""))[:200],
                "comment": entry.get("comment", ""),
            })

    return events


def _extract_variable_paths(scripts: list[dict]) -> list[str]:
    """Extract variable paths from tavern_helper scripts.

    Looks for registerMvuSchema() calls and extracts field definitions.
    """
    paths: list[str] = []
    import re

    for script in scripts:
        if not isinstance(script, dict):
            continue
        content = script.get("content", "")
        if not content or "registerMvuSchema" not in content:
            continue

        # Extract z.object({...}) field names
        field_matches = re.findall(r'(\w+)\s*:\s*z\.', content)
        for fm in field_matches:
            if fm not in paths and not fm.startswith("_"):
                paths.append(fm)

    return paths


def _extract_phase_triggers(phases: list[dict]) -> list[dict[str, str]]:
    """Build phase transition triggers from detected phases.

    Returns list of {from_phase, to_phase, condition_description}.
    """
    triggers: list[dict[str, str]] = []
    for i in range(len(phases) - 1):
        triggers.append({
            "from": phases[i]["phase"],
            "to": phases[i + 1]["phase"],
            "condition": f"从阶段{phases[i]['phase']}自然推进到阶段{phases[i+1]['phase']}",
        })
    return triggers


def build_card_structure_context(structure: dict[str, Any]) -> str:
    """Convert detected card structure into a prompt-usable context string."""
    if not structure.get("has_structure"):
        return ""

    parts: list[str] = ["## Card Structure Analysis"]

    if structure.get("phases"):
        parts.append("### Character Phases")
        for p in structure["phases"]:
            parts.append(f"- Phase {p['phase']}: {p['description'][:100]}")

    if structure.get("events"):
        parts.append("### Event Library")
        for e in structure["events"][:10]:
            parts.append(f"- {e['key']}: {e['content'][:100]}")

    if structure.get("phase_triggers"):
        parts.append("### Phase Triggers")
        for t in structure["phase_triggers"]:
            parts.append(f"- {t['from']} → {t['to']}: {t['condition']}")

    return "\n".join(parts)
