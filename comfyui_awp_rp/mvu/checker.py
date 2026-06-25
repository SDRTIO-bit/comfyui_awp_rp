"""
MVU Variable Checklist Generator.

Port of oh-story-claudecode mvu_check.py. Generates a compact variable-path
checklist that the AI can use during generation to ensure every narrative-touched
variable has a corresponding _.set() / _.add() command.

Usage:
    from comfyui_awp_rp.mvu.checker import generate_variable_checklist
    checklist = generate_variable_checklist(initvar, audit)
"""

from __future__ import annotations

from typing import Any


def _collect_leaf_paths(data: Any, prefix: str = "") -> list[tuple[str, str, Any]]:
    """Recursively collect all leaf paths from a nested dict.

    Returns list of (path, type_name, value) tuples.
    """
    paths: list[tuple[str, str, Any]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                paths.extend(_collect_leaf_paths(v, full))
            else:
                paths.append((full, type(v).__name__, v))
    return paths


def generate_variable_checklist(
    initvar: dict,
    audit: dict | None = None,
) -> dict:
    """Generate a variable checklist for the AI generation step.

    Args:
        initvar: Initial variable structure (nested dict of current values).
        audit: Optional audit from audit_variables() containing "sections"
            with touched/untouched flags.

    Returns:
        Dict with: sections, touched_last_turn, untouched_last_turn,
        total_paths, checklist (markdown string), reminder.
    """
    sections: dict[str, dict] = {}
    all_paths: list[str] = []

    for section_name, section_data in (initvar or {}).items():
        leaves = _collect_leaf_paths(section_data, section_name)
        sections[section_name] = {
            "path_count": len(leaves),
            "paths": [(p, t) for p, t, _ in leaves],
            "sample_values": {p: v for p, _, v in leaves if not isinstance(v, (dict, list))},
        }
        all_paths.extend([p for p, _, _ in leaves])

    # Determine which sections were touched last turn
    touched_sections: list[str] = []
    untouched_sections: list[str] = []
    if audit and audit.get("sections"):
        for name, info in audit["sections"].items():
            if info.get("touched"):
                touched_sections.append(name)
            else:
                untouched_sections.append(name)
    else:
        untouched_sections = list(sections.keys())

    # Build compact checklist
    checklist_lines: list[str] = []
    for name, info in sections.items():
        flag = "[✓]" if name in touched_sections else "[ ]"
        sample = ", ".join(
            f"{p.rsplit('.', 1)[-1]}={v}"
            for p, v in list(info["sample_values"].items())[:5]
        )
        checklist_lines.append(f"  {flag} {name} ({info['path_count']} paths): {sample}")

    return {
        "sections": list(sections.keys()),
        "touched_last_turn": touched_sections,
        "untouched_last_turn": untouched_sections,
        "total_paths": len(all_paths),
        "checklist": "\n".join(checklist_lines),
        "reminder": (
            "For EVERY variable path whose value changes in the narrative, write a "
            "_.set() or _.add() command. Check each section above — if the narrative "
            "touches it, you MUST have a command for it. Especially numeric fields "
            "(inventory counts, HP, money, visit counters)."
        ),
    }
