"""
Story System Contracts — three-layer contract tree for narrative governance.

Port of webnovel-writer's story-system contract architecture:
  MASTER_SETTING.json  → World-level rules and constraints
  volume_{NNN}.json    → Volume-level pacing and arcs
  chapter_{NNN}.json   → Chapter-level directives and must-cover nodes

Contracts are resolved at runtime: chapter > volume > master precedence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ChapterDirective:
    """Chapter-level writing directive."""
    goal: str = ""
    time_anchor: str = ""
    chapter_span: str = ""
    countdown: str = ""
    chapter_end_open_question: str = ""


@dataclass
class RuntimeContract:
    """Resolved runtime contract for a specific chapter.

    Merges MASTER → volume → chapter with precedence layers.
    """
    chapter_num: int = 0
    genre: str = ""
    chapter_directive: ChapterDirective = field(default_factory=ChapterDirective)
    must_cover_nodes: list[str] = field(default_factory=list)
    forbidden_zones: list[str] = field(default_factory=list)
    style_priority: str = ""
    pacing_strategy: str = ""
    anti_patterns: list[str] = field(default_factory=list)
    writing_guidance: str = ""
    active_rules: list[str] = field(default_factory=list)
    # Source tracking
    sources: dict[str, str] = field(default_factory=dict)


class StoryContracts:
    """Three-layer contract system for narrative governance."""

    def __init__(self, project_root: str):
        self._root = os.path.join(project_root, ".story-system")
        self._master: dict[str, Any] = {}
        self._volumes: dict[int, dict[str, Any]] = {}
        self._chapters: dict[int, dict[str, Any]] = {}

    def load_all(self) -> int:
        """Load all available contracts. Returns number loaded."""
        count = 0
        os.makedirs(self._root, exist_ok=True)

        # Load master
        master_path = os.path.join(self._root, "MASTER_SETTING.json")
        if os.path.exists(master_path):
            try:
                with open(master_path, "r", encoding="utf-8") as f:
                    self._master = json.load(f)
                count += 1
            except (json.JSONDecodeError, OSError):
                pass

        # Load volume contracts
        for fname in sorted(os.listdir(self._root)):
            if fname.startswith("volume_") and fname.endswith(".json"):
                try:
                    vol_num = int(fname.replace("volume_", "").replace(".json", ""))
                    with open(os.path.join(self._root, fname), "r", encoding="utf-8") as f:
                        self._volumes[vol_num] = json.load(f)
                    count += 1
                except (ValueError, json.JSONDecodeError, OSError):
                    pass

        # Load chapter contracts
        for fname in sorted(os.listdir(self._root)):
            if fname.startswith("chapter_") and fname.endswith(".json"):
                try:
                    ch_num = int(fname.replace("chapter_", "").replace(".json", ""))
                    with open(os.path.join(self._root, fname), "r", encoding="utf-8") as f:
                        self._chapters[ch_num] = json.load(f)
                    count += 1
                except (ValueError, json.JSONDecodeError, OSError):
                    pass

        return count

    def resolve(self, chapter_num: int, genre: str = "") -> RuntimeContract:
        """Resolve runtime contract for a chapter.

        Precedence: chapter_directive > volume > master.

        Args:
            chapter_num: Chapter number to resolve.
            genre: Genre override (e.g., "仙侠", "都市").

        Returns:
            Merged RuntimeContract.
        """
        rc = RuntimeContract(chapter_num=chapter_num, genre=genre)

        # Layer 1: Master
        if self._master:
            rc.forbidden_zones = self._master.get("forbidden_zones", [])
            rc.anti_patterns = self._master.get("anti_patterns", [])
            rc.active_rules = self._master.get("active_rules", [])
            rc.sources["master"] = "MASTER_SETTING.json"

        # Layer 2: Volume
        vol_num = max(1, (chapter_num - 1) // 100 + 1)
        volume = self._volumes.get(vol_num)
        if volume:
            rc.pacing_strategy = volume.get("pacing_strategy", rc.pacing_strategy)
            rc.style_priority = volume.get("style_priority", rc.style_priority)
            if volume.get("forbidden_zones"):
                rc.forbidden_zones.extend(volume["forbidden_zones"])
            if volume.get("anti_patterns"):
                rc.anti_patterns.extend(volume["anti_patterns"])
            rc.sources["volume"] = f"volume_{vol_num:03d}.json"

        # Layer 3: Chapter
        chapter = self._chapters.get(chapter_num)
        if chapter:
            cd = chapter.get("chapter_directive", {})
            if isinstance(cd, dict):
                rc.chapter_directive = ChapterDirective(
                    goal=cd.get("goal", ""),
                    time_anchor=cd.get("time_anchor", ""),
                    chapter_span=cd.get("chapter_span", ""),
                    countdown=cd.get("countdown", ""),
                    chapter_end_open_question=cd.get("chapter_end_open_question", ""),
                )
            rc.must_cover_nodes = chapter.get("must_cover_nodes", [])
            if chapter.get("forbidden_zones"):
                rc.forbidden_zones.extend(chapter["forbidden_zones"])
            rc.sources["chapter"] = f"chapter_{chapter_num:04d}.json"

        # Deduplicate
        rc.forbidden_zones = list(dict.fromkeys(rc.forbidden_zones))
        rc.anti_patterns = list(dict.fromkeys(rc.anti_patterns))

        return rc

    def render_contract_context(self, rc: RuntimeContract) -> str:
        """Convert a RuntimeContract into a prompt-injectable string."""
        parts: list[str] = []

        if rc.chapter_directive.goal:
            parts.append(f"## Chapter Directive\n- Goal: {rc.chapter_directive.goal}")
            if rc.chapter_directive.time_anchor:
                parts.append(f"- Time: {rc.chapter_directive.time_anchor}")
            if rc.chapter_directive.chapter_end_open_question:
                parts.append(f"- End Hook: {rc.chapter_directive.chapter_end_open_question}")

        if rc.must_cover_nodes:
            parts.append(f"## Must Cover\n- " + "\n- ".join(rc.must_cover_nodes))

        if rc.forbidden_zones:
            parts.append(f"## Forbidden\n- " + "\n- ".join(rc.forbidden_zones[:5]))

        if rc.pacing_strategy:
            parts.append(f"## Pacing\n{rc.pacing_strategy}")

        if rc.style_priority:
            parts.append(f"## Style Priority\n{rc.style_priority}")

        if rc.anti_patterns:
            parts.append(f"## Avoid\n- " + "\n- ".join(rc.anti_patterns[:5]))

        return "\n\n".join(parts)

    def save_master(self, data: dict[str, Any]) -> None:
        """Save master contract."""
        os.makedirs(self._root, exist_ok=True)
        with open(os.path.join(self._root, "MASTER_SETTING.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_chapter(self, chapter_num: int, data: dict[str, Any]) -> None:
        """Save a chapter contract."""
        os.makedirs(self._root, exist_ok=True)
        fname = f"chapter_{chapter_num:04d}.json"
        with open(os.path.join(self._root, fname), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_volume(self, volume_num: int, data: dict[str, Any]) -> None:
        """Save a volume contract."""
        os.makedirs(self._root, exist_ok=True)
        fname = f"volume_{volume_num:03d}.json"
        with open(os.path.join(self._root, fname), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
