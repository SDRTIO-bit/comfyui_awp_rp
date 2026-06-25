"""
MVU Variable-Driven Worldbook Matcher.

Port of oh-story-claudecode match_worldbook.py. When variables change,
extract topics from changed paths/values and match against a worldbook
index to find related entries for the next turn's context.

Usage:
    from comfyui_awp_rp.mvu.matcher import match_worldbook_by_variables
    matches = match_worldbook_by_variables(var_audit, worldbook_index)
"""

from __future__ import annotations

import re
from typing import Any


def extract_topics_from_changes(audit: dict, initvar: dict | None = None) -> list[str]:
    """Extract search topics from variable change audit.

    Topics are extracted from:
    - Changed path segments (e.g., "璃夏.好感度" → ["璃夏", "好感度"])
    - Changed values (if string, split into words)
    - Section names from initvar

    Args:
        audit: Output from audit_variables() — must contain "changed" dict.
        initvar: Optional initial variable structure for section names.

    Returns:
        Deduplicated list of topic strings.
    """
    topics: list[str] = []

    changed = audit.get("changed", {})
    for path, change in changed.items():
        # Path segments as topics
        segments = [s for s in path.split(".") if s and not s.startswith("_")]
        for seg in segments:
            if seg not in topics and len(seg) >= 1:
                topics.append(seg)

        # New string values → extract meaningful words
        new_val = change.get("new")
        if isinstance(new_val, str) and len(new_val) < 200:
            words = re.split(r"[，、。；;！!？?\s]+", new_val)
            for w in words:
                w = w.strip()
                if len(w) >= 2 and w not in topics:
                    topics.append(w)

    # Section names from initvar
    if initvar:
        for section_name in initvar:
            if section_name not in topics:
                topics.append(section_name)

    return topics


def score_match(keyword: str, topics: list[str]) -> tuple[int, str]:
    """Score a worldbook keyword against topic list.

    Scoring tiers:
    - 10: exact match
    - 7:  keyword is substring of topic
    - 6:  topic is substring of keyword
    - 3-5: CJK character overlap (≥2 shared characters)

    Returns:
        (score, reason_string) where reason explains best match.
    """
    best_score = 0
    best_reason = ""

    for topic in topics:
        if not topic:
            continue

        # Exact match
        if keyword == topic:
            if best_score < 10:
                best_score = 10
                best_reason = f"exact match: {topic}"

        # Keyword is substring of topic
        elif keyword in topic:
            s = 7
            if s > best_score:
                best_score = s
                best_reason = f"keyword in topic: {topic}"

        # Topic is substring of keyword
        elif topic in keyword:
            s = 6
            if s > best_score:
                best_score = s
                best_reason = f"topic in keyword: {topic}"

        # CJK character overlap
        elif len(keyword) >= 2 and len(topic) >= 2:
            overlap = sum(1 for c in keyword if c in topic)
            if overlap >= 2:
                s = 3 + overlap
                if s > best_score:
                    best_score = s
                    best_reason = f"char overlap({overlap}): {topic}"

    return best_score, best_reason


# Noise keywords that are present in most worldbook indexes but rarely
# useful for narrative context matching.
_SKIP_KEYWORDS = {
    "[initvar]变量初始化勿开",
    "[mvu_update]变量更新规则",
    "[mvu_update]变量输出格式",
    "[mvu_update]变量输出格式强调",
    "变量列表",
}


def match_worldbook_by_variables(
    audit: dict,
    worldbook_index: list[dict[str, Any]],
    initvar: dict | None = None,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Match worldbook entries against variable changes.

    Args:
        audit: Output from audit_variables().
        worldbook_index: List of worldbook entry dicts, each must have at
            least "keyword" and "title" keys. Optional: "section", "one_liner".
        initvar: Optional initial variable structure for section-name topics.
        top_n: Number of top matches to return.

    Returns:
        List of matched entries with scoring info, sorted by score desc.
        Format: [{keyword, title, section, one_liner, score, reason}, ...]
    """
    if not worldbook_index:
        return []

    topics = extract_topics_from_changes(audit, initvar)

    results: list[dict[str, Any]] = []
    for entry in worldbook_index:
        kw = entry.get("keyword", "")
        if kw in _SKIP_KEYWORDS:
            continue
        score, reason = score_match(kw, topics)
        if score > 0:
            results.append({
                "keyword": kw,
                "title": entry.get("title", kw),
                "section": entry.get("section", f"## {kw}"),
                "one_liner": entry.get("one_liner", ""),
                "score": score,
                "reason": reason,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
