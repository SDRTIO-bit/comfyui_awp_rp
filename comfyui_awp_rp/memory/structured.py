"""Structured memory for AWP RP (Phase 2).

Adds story_facts / open_threads / scene_state partitions on top of the
existing flat ``LongTermMemory`` store. Uses ``MemoryRecord.type`` for
partition identity and ``metadata`` (JSON dict) for partition-specific keys.
No new DB columns.

Idempotent merges prevent duplicate facts and threads. Scene state is a
singleton upsert. All writes are validated before storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..core.types import MemoryRecord
from ..core.store import SQLiteStore, get_store
from .long_term import LongTermMemory


# ── Schema helpers ──────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _id_key(*parts: str) -> str:
    return hashlib.md5("|".join(_norm(p) for p in parts).encode()).hexdigest()[:16]


# ── Structured data classes ─────────────────────────────────────────────────

@dataclass
class StoryFact:
    """A canonical, durable fact derived from narrative events."""

    summary: str               # ≤200 chars
    entity_ids: list[str] = field(default_factory=list)
    evidence_turn: int = 0
    confidence: float = 0.7    # 0.0–1.0
    importance: float = 0.5    # 0.0–1.0
    tags: list[str] = field(default_factory=list)
    source_kind: str = "event"  # event | relationship-change | state-change | discovery

    @property
    def fact_key(self) -> str:
        return _id_key(self.summary, *sorted(self.entity_ids))

    def to_record(self, namespace: str) -> MemoryRecord:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return MemoryRecord(
            id=f"fact_{self.fact_key}",
            namespace=namespace,
            content=self.summary,
            title=self.summary[:50],
            type="story_fact",
            tags=self.tags,
            entity_ids=self.entity_ids,
            importance=self.importance,
            created_at=now,
            updated_at=now,
            metadata={
                "fact_key": self.fact_key,
                "evidence_turn": self.evidence_turn,
                "confidence": self.confidence,
                "source_kind": self.source_kind,
            },
        )


@dataclass
class OpenThread:
    """An unresolved (or resolved) narrative thread."""

    topic: str
    entity_ids: list[str] = field(default_factory=list)
    status: str = "open"       # open | resolved | abandoned
    created_turn: int = 0
    resolved_turn: Optional[int] = None
    priority: float = 0.5

    @property
    def thread_key(self) -> str:
        return _id_key(self.topic, *sorted(self.entity_ids))

    def to_record(self, namespace: str) -> MemoryRecord:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return MemoryRecord(
            id=f"thread_{self.thread_key}",
            namespace=namespace,
            content=self.topic,
            title=self.topic[:50],
            type="open_thread",
            entity_ids=self.entity_ids,
            importance=self.priority,
            created_at=now,
            updated_at=now,
            metadata={
                "thread_key": self.thread_key,
                "status": self.status,
                "created_turn": self.created_turn,
                "resolved_turn": self.resolved_turn,
                "priority": self.priority,
            },
        )


@dataclass
class SceneState:
    """Current scene context — singleton per namespace."""

    location: str = ""
    time_of_day: str = ""
    weather: str = ""
    characters_present: list[str] = field(default_factory=list)
    mood: str = ""
    narrative_summary: str = ""
    last_updated_turn: int = 0

    def to_record(self, namespace: str) -> MemoryRecord:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return MemoryRecord(
            id="scene_state",
            namespace=namespace,
            content=self.narrative_summary or self.location,
            title=f"[Scene] {self.location}",
            type="scene_state",
            entity_ids=self.characters_present,
            importance=0.8,
            created_at=now,
            updated_at=now,
            metadata={
                "location": self.location,
                "time_of_day": self.time_of_day,
                "weather": self.weather,
                "characters_present": self.characters_present,
                "mood": self.mood,
                "narrative_summary": self.narrative_summary,
                "last_updated_turn": self.last_updated_turn,
            },
        )


# ── Validation ──────────────────────────────────────────────────────────────

def validate_story_fact(candidate: dict[str, Any]) -> tuple[bool, str, Optional[StoryFact]]:
    summary = str(candidate.get("summary") or "").strip()
    if not summary:
        return False, "missing summary", None
    if len(summary) > 300:
        summary = summary[:297] + "…"
    entity_ids = candidate.get("entityIds") or candidate.get("entity_ids") or []
    if not isinstance(entity_ids, list) or not entity_ids:
        return False, "empty entityIds", None
    entity_ids = [str(e) for e in entity_ids]

    kind = str(candidate.get("kind") or "event")
    allowed = {"event", "relationship-change", "state-change", "commitment", "discovery"}
    if kind not in allowed:
        return False, f"unknown kind: {kind}", None

    fact = StoryFact(
        summary=summary,
        entity_ids=entity_ids,
        confidence=float(candidate.get("confidence", 0.7)),
        importance=float(candidate.get("importance", 0.5)),
        tags=list(candidate.get("tags") or []) if isinstance(candidate.get("tags"), list) else [],
        source_kind=kind,
    )
    return True, "", fact


def validate_open_thread(candidate: dict[str, Any]) -> tuple[bool, str, Optional[OpenThread]]:
    topic = str(candidate.get("summary") or candidate.get("topic") or "").strip()
    if not topic:
        return False, "missing topic", None
    if len(topic) > 300:
        topic = topic[:297] + "…"
    entity_ids = candidate.get("entityIds") or candidate.get("entity_ids") or []
    if not isinstance(entity_ids, list) or not entity_ids:
        return False, "empty entityIds", None
    entity_ids = [str(e) for e in entity_ids]

    kind = str(candidate.get("kind") or "")
    if kind != "unresolved-thread":
        return False, f"not a thread kind: {kind}", None

    thread = OpenThread(
        topic=topic,
        entity_ids=entity_ids,
        status="open",
        priority=float(candidate.get("importance", 0.5)),
    )
    return True, "", thread


def validate_scene_state(candidate: dict[str, Any]) -> tuple[bool, str, Optional[SceneState]]:
    location = str(candidate.get("location") or "").strip()
    if not location:
        loc2 = str(candidate.get("summary") or "").strip()
        if loc2:
            location = loc2

    scene = SceneState(
        location=location,
        time_of_day=str(candidate.get("time_of_day") or ""),
        weather=str(candidate.get("weather") or ""),
        characters_present=(
            list(candidate.get("characters_present", []))
            if isinstance(candidate.get("characters_present"), list) else []
        ),
        mood=str(candidate.get("mood") or ""),
        narrative_summary=str(candidate.get("narrative_summary") or candidate.get("summary") or ""),
    )
    return True, "", scene


# ── StructuredMemoryManager ─────────────────────────────────────────────────

class StructuredMemoryManager:
    """Manages structured memory partitions backed by ``LongTermMemory``."""

    def __init__(self, store: Optional[SQLiteStore] = None) -> None:
        self._ltm = LongTermMemory(store=store)

    # ── Story facts ────────────────────────────────────────────────────

    def write_story_fact(self, namespace: str, fact: StoryFact) -> tuple[MemoryRecord, bool]:
        """Write or update a story fact. Idempotent by ``fact.fact_key``.

        Returns ``(record, is_new)``.
        """
        existing = self._find_by_metadata_key(namespace, "story_fact", "fact_key", fact.fact_key)
        if existing:
            # Merge: max confidence/importance, union tags
            existing.metadata["confidence"] = max(
                float(existing.metadata.get("confidence", 0.7)), fact.confidence
            )
            existing.importance = max(
                float(existing.importance or 0.5), fact.importance
            )
            existing_tags = set(existing.tags or [])
            existing_tags.update(fact.tags or [])
            existing.tags = sorted(existing_tags)
            # Update evidence turn to latest
            existing.metadata["evidence_turn"] = max(
                int(existing.metadata.get("evidence_turn", 0)), fact.evidence_turn
            )
            from datetime import datetime, timezone
            existing.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._ltm._store.upsert_memory(namespace, [existing])
            return existing, False
        else:
            record = fact.to_record(namespace)
            self._ltm._store.upsert_memory(namespace, [record])
            return record, True

    def query_story_facts(
        self, namespace: str, entity_ids: Optional[list[str]] = None, limit: int = 20,
    ) -> list[MemoryRecord]:
        records = self._ltm.query(namespace=namespace, type_filter="story_fact", limit=limit * 2)
        if entity_ids:
            eids = set(entity_ids)
            records = [r for r in records if eids & set(r.entity_ids or [])]
        return records[:limit]

    # ── Open threads ───────────────────────────────────────────────────

    def write_open_thread(self, namespace: str, thread: OpenThread) -> tuple[MemoryRecord, bool]:
        """Write or update a thread. Idempotent by ``thread.thread_key``.

        Returns ``(record, is_new)``.
        """
        existing = self._find_by_metadata_key(namespace, "open_thread", "thread_key", thread.thread_key)
        if existing:
            old_status = existing.metadata.get("status", "open")
            new_status = thread.status
            if old_status == "open" and new_status == "resolved":
                existing.metadata["status"] = "resolved"
                existing.metadata["resolved_turn"] = thread.resolved_turn
                from datetime import datetime, timezone
                existing.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self._ltm._store.upsert_memory(namespace, [existing])
            # else: no change — keep existing
            return existing, False
        else:
            record = thread.to_record(namespace)
            self._ltm._store.upsert_memory(namespace, [record])
            return record, True

    def resolve_thread(self, namespace: str, thread_key: str, turn: int) -> bool:
        existing = self._find_by_metadata_key(namespace, "open_thread", "thread_key", thread_key)
        if existing and existing.metadata.get("status") == "open":
            existing.metadata["status"] = "resolved"
            existing.metadata["resolved_turn"] = turn
            from datetime import datetime, timezone
            existing.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._ltm._store.upsert_memory(namespace, [existing])
            return True
        return False

    def query_open_threads(
        self, namespace: str, status: str = "open", limit: int = 20,
    ) -> list[MemoryRecord]:
        records = self._ltm.query(namespace=namespace, type_filter="open_thread", limit=limit * 2)
        return [r for r in records if r.metadata.get("status") == status][:limit]

    # ── Scene state ────────────────────────────────────────────────────

    def write_scene_state(self, namespace: str, scene: SceneState) -> MemoryRecord:
        existing = self._find_one_by_type(namespace, "scene_state")
        record = scene.to_record(namespace)
        if existing:
            record.id = existing.id
            record.created_at = existing.created_at
        self._ltm._store.upsert_memory(namespace, [record])
        return record

    def get_scene_state(self, namespace: str) -> Optional[SceneState]:
        rec = self._find_one_by_type(namespace, "scene_state")
        if not rec:
            return None
        m = rec.metadata or {}
        return SceneState(
            location=str(m.get("location") or rec.content or ""),
            time_of_day=str(m.get("time_of_day") or ""),
            weather=str(m.get("weather") or ""),
            characters_present=list(m.get("characters_present") or []),
            mood=str(m.get("mood") or ""),
            narrative_summary=str(m.get("narrative_summary") or rec.content or ""),
            last_updated_turn=int(m.get("last_updated_turn", 0)),
        )

    # ── Bulk ingest from curator output ────────────────────────────────

    def ingest_curator_candidates(
        self, namespace: str, candidates: list[dict[str, Any]], turn_index: int,
    ) -> dict[str, Any]:
        """Validate and write curator-produced candidates.

        Returns ``{written, updated, rejected, errors}``.
        """
        stats = {"written": 0, "updated": 0, "rejected": 0, "errors": []}
        for idx, cand in enumerate(candidates):
            if not isinstance(cand, dict):
                stats["rejected"] += 1
                stats["errors"].append(f"[{idx}] not a dict")
                continue

            kind = str(cand.get("kind") or "event")
            try:
                if kind == "unresolved-thread":
                    ok, err, thread = validate_open_thread(cand)
                    if not ok:
                        stats["rejected"] += 1
                        stats["errors"].append(f"[{idx}] thread: {err}")
                        continue
                    assert thread is not None
                    thread.created_turn = turn_index
                    _, is_new = self.write_open_thread(namespace, thread)
                elif kind == "scene-state-change":
                    ok, err, scene = validate_scene_state(cand)
                    if not ok:
                        stats["rejected"] += 1
                        stats["errors"].append(f"[{idx}] scene: {err}")
                        continue
                    assert scene is not None
                    scene.last_updated_turn = turn_index
                    self.write_scene_state(namespace, scene)
                    is_new = True
                else:
                    # Default: treat as story fact
                    ok, err, fact = validate_story_fact(cand)
                    if not ok:
                        stats["rejected"] += 1
                        stats["errors"].append(f"[{idx}] fact: {err}")
                        continue
                    assert fact is not None
                    fact.evidence_turn = turn_index
                    _, is_new = self.write_story_fact(namespace, fact)

                if is_new:
                    stats["written"] += 1
                else:
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001 — fail per-record
                stats["rejected"] += 1
                stats["errors"].append(f"[{idx}] exception: {exc}")

        return stats

    # ── Internal helpers ───────────────────────────────────────────────

    def _find_by_metadata_key(
        self, namespace: str, type_filter: str, key: str, value: str,
    ) -> Optional[MemoryRecord]:
        records = self._ltm.query(namespace=namespace, type_filter=type_filter, limit=100)
        for r in records:
            if r.metadata.get(key) == value:
                return r
        return None

    def _find_one_by_type(self, namespace: str, type_filter: str) -> Optional[MemoryRecord]:
        records = self._ltm.query(namespace=namespace, type_filter=type_filter, limit=1)
        return records[0] if records else None
