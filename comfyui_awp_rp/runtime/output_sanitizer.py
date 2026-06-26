"""Conservative output sanitization for RP replies.

Two-tier, fail-safe cleanup. This does NOT ask the model to emit a visible
thinking chain and does NOT rely on frontend hiding — it only inspects the
final text the writer produced.

Tiers
-----
A. Explicit process tags (``<thinking>``, ``<analysis>``, ``<tool>``,
   ``<tool_call>``): hard failure → request one bounded retry.
B. Leading meta-phrases ("好，现在", "让我", "进入角色", ...): conservative
   prefix scrub — only strips an obvious meta opener at the very start, never
   a broad cross-paragraph regex.

Guards
------
- Natural narrative like "我想了想" or "让他进入房间" must NOT be deleted.
- If after scrub the text is empty / too short / structurally broken → fail.
- Retries are bounded (default 1) and never loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SanitizerAction(str, Enum):
    ACCEPT = "accept"
    SCRUB_PREFIX = "scrub_prefix"
    REJECT_RETRY = "reject_retry"
    REJECT_GIVE_UP = "reject_give_up"


@dataclass
class SanitizerVerdict:
    action: SanitizerAction
    cleaned_text: str
    reasons: list[str]
    removed_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "cleaned_text": self.cleaned_text,
            "reasons": self.reasons,
            "removed_snippet": self.removed_snippet[:120],
        }


# ── Tier A: explicit process / tool tags → hard reject ─────────────────────
# Also: advice leak patterns — narrow, compound phrases that only appear in
# internal agent-to-agent communication. Single-word matches like "评审" or
# "导演" alone are NOT flagged.
ADVICE_LEAK_PATTERNS = (
    "评审认为",
    "导演建议",
    "内部建议",
    "子 Agent",
    "子Agent",
    "subagent advice",
    "critic advice",
    "director advice",
    "[advice]",
)


def _has_advice_leak(text: str) -> str | None:
    """Check if output contains internal advice meta-discourse phrases.

    Scans first 500 chars (header area) + any `[...]` bracket markers
    throughout. Returns the matched phrase or ``None``.
    """
    head = text[:500]
    for phrase in ADVICE_LEAK_PATTERNS:
        if phrase in head:
            return phrase
    # Also scan for bracket-labelled advice in full text
    for phrase in ("[评审]", "[导演]", "[critic]", "[director]", "[advice]"):
        if phrase in text:
            return phrase
    return None


# ── Tier A: explicit process / tool tags → hard reject ─────────────────────
EXPLICIT_TAG_PATTERNS = (
    re.compile(r"<thinking\b[^>]*>", re.IGNORECASE),
    re.compile(r"<think\b[^>]*>", re.IGNORECASE),
    re.compile(r"<analysis\b[^>]*>", re.IGNORECASE),
    re.compile(r"<plan\b[^>]*>", re.IGNORECASE),
    re.compile(r"<tool_call\b[^>]*>", re.IGNORECASE),
    re.compile(r"<tool\b[^>*>]", re.IGNORECASE),
    re.compile(r"```json", re.IGNORECASE),
    re.compile(r"\[Status:", re.IGNORECASE),
)

# ── Tier B: leading meta-phrases ────────────────────────────────────────────
# Matched only at the very start of the text (after whitespace), and only when
# followed by a meta verb pattern. Single-line, first paragraph only.
LEADING_META_PATTERNS = [
    re.compile(r"^\s*(好[，,]?\s*现在|好[，,]?\s*让我们|好[，,]?\s*我[们来])"),
    re.compile(r"^\s*(让我[来们]?|我先|我需要|我将|接下来我将|接下来我)"),
    re.compile(r"^\s*(作为(?:一个)?(?:AI|助手|写手|模型))"),
    re.compile(r"^\s*(根据(?:设定|你的要求|要求|上下文))"),
    re.compile(r"^\s*(开始(?:生成|叙事|写作|进入)|进入角色|进入故事)"),
    re.compile(r"^\s*(以下是|下面是|首先[，,])"),
]

MIN_VALID_LENGTH = 20  # below this after scrub → reject


def _has_explicit_tag(text: str) -> str | None:
    for pat in EXPLICIT_TAG_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def _try_scrub_prefix(text: str) -> tuple[str, str]:
    """Strip a single leading meta opener from the first paragraph only.

    Returns (cleaned, removed). If nothing matches, returns (text, "").
    Only the very first non-empty line is considered; we never touch later
    paragraphs (so "让他进入房间" mid-text is safe).
    """
    if not text:
        return text, ""
    # Work on the first line only
    lines = text.split("\n", 1)
    first = lines[0]
    rest = lines[1] if len(lines) > 1 else ""

    for pat in LEADING_META_PATTERNS:
        m = pat.match(first)
        if not m:
            continue
        removed = m.group(0)
        remainder = first[m.end():].lstrip("，,。:： \t")
        # If scrubbing the opener leaves the first line empty, drop the line
        # entirely and keep the rest of the text.
        if not remainder.strip():
            cleaned = rest.lstrip("\n")
        else:
            cleaned = remainder + ("\n" + rest if rest else "")
        if cleaned.strip():
            return cleaned, removed
    return text, ""


def sanitize_output(
    text: str,
    *,
    attempt: int = 0,
    max_retries: int = 1,
) -> SanitizerVerdict:
    """Inspect and clean a writer reply.

    Args:
        text: The raw writer output.
        attempt: 0-based retry attempt counter (caller-managed).
        max_retries: Max retries allowed. When exceeded, a persistent failure
            returns ``REJECT_GIVE_UP`` with a diagnostic.

    Returns:
        A :class:`SanitizerVerdict` describing the action and cleaned text.
    """
    raw = str(text or "")
    reasons: list[str] = []

    # Tier A: explicit tags
    tag = _has_explicit_tag(raw)
    if tag:
        reasons.append(f"explicit-tag: {tag}")
        if attempt >= max_retries:
            return SanitizerVerdict(
                action=SanitizerAction.REJECT_GIVE_UP,
                cleaned_text=raw,
                reasons=reasons + ["retry-limit-exceeded"],
                removed_snippet=tag,
            )
        return SanitizerVerdict(
            action=SanitizerAction.REJECT_RETRY,
            cleaned_text=raw,
            reasons=reasons,
            removed_snippet=tag,
        )

    # Tier A2: advice leak (internal meta-discourse in output)
    leak = _has_advice_leak(raw)
    if leak:
        reasons.append(f"advice-leak: {leak}")
        if attempt >= max_retries:
            return SanitizerVerdict(
                action=SanitizerAction.REJECT_GIVE_UP,
                cleaned_text=raw,
                reasons=reasons + ["retry-limit-exceeded"],
                removed_snippet=leak,
            )
        return SanitizerVerdict(
            action=SanitizerAction.REJECT_RETRY,
            cleaned_text=raw,
            reasons=reasons,
            removed_snippet=leak,
        )

    # Empty before any scrub
    if not raw.strip():
        reasons.append("empty-output")
        if attempt >= max_retries:
            return SanitizerVerdict(
                action=SanitizerAction.REJECT_GIVE_UP,
                cleaned_text=raw,
                reasons=reasons + ["retry-limit-exceeded"],
            )
        return SanitizerVerdict(
            action=SanitizerAction.REJECT_RETRY,
            cleaned_text=raw,
            reasons=reasons,
        )

    # Tier B: conservative prefix scrub
    cleaned, removed = _try_scrub_prefix(raw)
    if removed:
        reasons.append(f"scrubbed-prefix: {removed.strip()[:30]}")
        if not cleaned.strip() or len(cleaned.strip()) < MIN_VALID_LENGTH:
            # Scrub left too little → treat as failure
            reasons.append("post-scrub-too-short")
            if attempt >= max_retries:
                return SanitizerVerdict(
                    action=SanitizerAction.REJECT_GIVE_UP,
                    cleaned_text=cleaned,
                    reasons=reasons + ["retry-limit-exceeded"],
                    removed_snippet=removed,
                )
            return SanitizerVerdict(
                action=SanitizerAction.REJECT_RETRY,
                cleaned_text=cleaned,
                reasons=reasons,
                removed_snippet=removed,
            )
        return SanitizerVerdict(
            action=SanitizerAction.SCRUB_PREFIX,
            cleaned_text=cleaned,
            reasons=reasons,
            removed_snippet=removed,
        )

    # No meta opener: verify minimum length
    if len(raw.strip()) < MIN_VALID_LENGTH:
        reasons.append("output-too-short")
        if attempt >= max_retries:
            return SanitizerVerdict(
                action=SanitizerAction.REJECT_GIVE_UP,
                cleaned_text=raw,
                reasons=reasons + ["retry-limit-exceeded"],
            )
        return SanitizerVerdict(
            action=SanitizerAction.REJECT_RETRY,
            cleaned_text=raw,
            reasons=reasons,
        )

    return SanitizerVerdict(
        action=SanitizerAction.ACCEPT,
        cleaned_text=raw,
        reasons=reasons or ["ok"],
    )
