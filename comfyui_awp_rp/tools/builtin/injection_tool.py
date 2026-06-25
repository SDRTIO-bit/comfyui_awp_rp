"""Injection rules tool — variable-driven worldbook context injection.

Port of oh-story-claudecode's apply_injections() mechanism. When variables
reach certain values (e.g. 性癖 changed), automatically inject relevant
worldbook entries into the next turn's context.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..registry import ToolRegistry, ToolDefinition


def get_injection_keywords(
    stat_data: dict[str, Any],
    injection_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract worldbook keywords from variable state using injection rules."""
    if not isinstance(stat_data, dict):
        stat_data = {}
    if not isinstance(injection_rules, list):
        injection_rules = []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for rule in injection_rules:
        if not isinstance(rule, dict):
            continue

        source_path = rule.get("source_path", "")
        split_pattern = rule.get("split_pattern", "[，、\\n]")
        prefix = rule.get("prefix", "")

        value = _lodash_get(stat_data, source_path)
        if not value or not isinstance(value, str) or not value.strip():
            continue

        try:
            if split_pattern.startswith("/") and split_pattern.rfind("/") > 0:
                last_slash = split_pattern.rfind("/")
                split_pattern = split_pattern[1:last_slash]
            keywords = re.split(split_pattern, value)
        except re.error:
            keywords = value.replace("，", ",").replace("、", ",").split(",")

        for kw in keywords:
            kw = kw.strip()
            if not kw:
                continue
            full_kw = prefix + kw if prefix and not kw.startswith(prefix) else kw
            if full_kw in seen:
                continue
            seen.add(full_kw)
            results.append({
                "keyword": full_kw,
                "source_path": source_path,
                "section": f"## {full_kw}",
            })

    return results


def resolve_injections(
    keywords: list[dict[str, Any]],
    worldbook_index: list[dict[str, Any]],
    max_entries: int = 3,
) -> list[dict[str, Any]]:
    """Resolve injection keywords to matching worldbook entries."""
    if not isinstance(keywords, list):
        keywords = []
    if not isinstance(worldbook_index, list):
        worldbook_index = []

    matches: list[dict[str, Any]] = []
    for kw_info in keywords:
        kw = kw_info.get("keyword", "") if isinstance(kw_info, dict) else str(kw_info)
        if not kw:
            continue

        for entry in worldbook_index:
            if not isinstance(entry, dict):
                continue
            entry_keywords = [str(entry.get("keyword", ""))]
            for key in ("tags", "keys", "keywords"):
                values = entry.get(key, [])
                if isinstance(values, str):
                    entry_keywords.append(values)
                elif isinstance(values, list):
                    entry_keywords.extend(str(item) for item in values)

            if any(ekw and (ekw == kw or kw in ekw or ekw in kw) for ekw in entry_keywords):
                matches.append({
                    "id": entry.get("id", ""),
                    "keyword": kw,
                    "title": entry.get("title", kw),
                    "section": entry.get("section", f"## {kw}"),
                    "one_liner": entry.get("one_liner") or entry.get("content", ""),
                    "source_path": kw_info.get("source_path", "") if isinstance(kw_info, dict) else "",
                })
                break

        if len(matches) >= max_entries:
            break

    return matches


def _get_injection_keywords(args: dict[str, Any]) -> str:
    """Extract injection keywords from variable state.

    Looks at configured source paths in the variable tree and splits
    their values to generate worldbook-matching keywords.
    """
    results = get_injection_keywords(
        args.get("stat_data", {}),
        args.get("injection_rules", []),
    )
    return json.dumps(results, ensure_ascii=False, indent=2)


def _lodash_get(obj: dict, path_str: str) -> Any:
    """Resolve dot-separated path from nested dict."""
    if not obj or not path_str:
        return None
    keys = path_str.split(".")
    current: Any = obj
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
        if current is None:
            return None
    return current


def _resolve_injections(args: dict[str, Any]) -> str:
    """Resolve injection keywords to full worldbook entry text.

    Given a list of keywords and a worldbook index, returns the
    matched entries with their full content (or section reference).
    """
    matches = resolve_injections(
        args.get("keywords", []),
        args.get("worldbook_index", []),
        args.get("max_entries", 3),
    )
    return json.dumps(matches, ensure_ascii=False, indent=2)


def register_injection_tools(registry: ToolRegistry) -> None:
    """Register injection rule tools."""
    registry.register(ToolDefinition(
        name="get_injection_keywords",
        description=(
            "Extract injection keywords from variable state. Looks at configured "
            "source paths (e.g. '世界设定.性癖') and splits their values into "
            "worldbook-matching keywords. Use this to auto-inject relevant setting "
            "entries based on current variable values."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stat_data": {
                    "type": "object",
                    "description": "Current variable state (stat_data dict).",
                },
                "injection_rules": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "List of injection rule objects, each with: "
                        "source_path (dot-separated variable path), "
                        "split_pattern (regex for splitting values), "
                        "prefix (optional keyword prefix)."
                    ),
                },
            },
            "required": ["stat_data"],
        },
        execute_fn=_get_injection_keywords,
        required_permissions=["worldbook:read"],
        category="injection",
    ))

    registry.register(ToolDefinition(
        name="resolve_injections",
        description=(
            "Resolve injection keywords to full worldbook entry references. "
            "Matches keywords against the worldbook index and returns the "
            "matched entries for context injection."
        ),
        parameters={
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Keyword list from get_injection_keywords.",
                },
                "worldbook_index": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Worldbook index entries.",
                },
                "max_entries": {
                    "type": "integer",
                    "description": "Maximum entries to return.",
                    "default": 3,
                },
            },
            "required": ["keywords", "worldbook_index"],
        },
        execute_fn=_resolve_injections,
        required_permissions=["worldbook:read"],
        category="injection",
    ))
