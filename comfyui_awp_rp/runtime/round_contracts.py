"""Data contracts for the V1 round orchestration layer.

All structures are plain dataclasses with JSON (de)serialization helpers and
default values, so old workflows that do not supply every field keep working.
``routing_trace`` is for logging/debugging only and must never reach the
player-visible narrative.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "awp-rp-routing.v1"


@dataclass
class SubAgentJob:
    """A single sub-agent delegation request produced by the router."""

    profile: str
    task: str
    task_type: str = "analysis"  # analysis | direction | review | extraction
    priority: str = "normal"     # normal | high
    max_result_tokens: int = 800

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubAgentResult:
    """Outcome of running one SubAgentJob. ``advice`` is internal-only."""

    profile: str
    task_type: str
    ok: bool
    advice: str = ""
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoundRoutingDecision:
    """Deterministic routing decision for a single RP turn.

    Produced by :func:`round_routing.build_round_routing_decision` without any
    LLM call. Drives whether memory/worldbook are read and which sub-agents
    (if any) run before the main writer.
    """

    schema_version: str = SCHEMA_VERSION
    should_read_memory: bool = False
    memory_queries: list[str] = field(default_factory=list)
    should_search_worldbook: bool = False
    worldbook_queries: list[str] = field(default_factory=list)
    subagent_jobs: list[SubAgentJob] = field(default_factory=list)
    should_run_continuity_check: bool = False
    should_scan_npc_activity: bool = False
    worldbook_budget_tokens: int = 4000
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.7
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["subagent_jobs"] = [j.to_dict() for j in self.subagent_jobs]
        return d

    @classmethod
    def from_dict(cls, data: Any) -> "RoundRoutingDecision":
        if not isinstance(data, dict):
            return cls()
        jobs_raw = data.get("subagent_jobs") or []
        jobs = [SubAgentJob(**j) for j in jobs_raw if isinstance(j, dict)]
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            should_read_memory=bool(data.get("should_read_memory", False)),
            memory_queries=list(data.get("memory_queries") or []),
            should_search_worldbook=bool(data.get("should_search_worldbook", False)),
            worldbook_queries=list(data.get("worldbook_queries") or []),
            subagent_jobs=jobs,
            should_run_continuity_check=bool(data.get("should_run_continuity_check", False)),
            should_scan_npc_activity=bool(data.get("should_scan_npc_activity", False)),
            worldbook_budget_tokens=int(data.get("worldbook_budget_tokens", 4000)),
            reasons=list(data.get("reasons") or []),
            confidence=float(data.get("confidence", 0.7)),
            trace=dict(data.get("trace") or {}),
        )


@dataclass
class RoundContextPacket:
    """Canonical context packet consumed by the main writer.

    ``context_owner`` records which path assembled this packet
    (``"routed"`` or ``"legacy"``). ``routing_trace`` is debug-only and must
    not be rendered into the narrative.
    """

    schema_version: str = SCHEMA_VERSION
    context_owner: str = "legacy"
    current_scene_state: dict[str, Any] = field(default_factory=dict)
    relationship_state: dict[str, Any] = field(default_factory=dict)
    open_threads: list[dict[str, Any]] = field(default_factory=list)
    recent_summary: str = ""
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)
    retrieved_worldbook_entries: list[dict[str, Any]] = field(default_factory=list)
    subagent_advice: list[dict[str, Any]] = field(default_factory=list)
    routing_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "RoundContextPacket":
        if not isinstance(data, dict):
            return cls()
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            context_owner=data.get("context_owner", "legacy"),
            current_scene_state=dict(data.get("current_scene_state") or {}),
            relationship_state=dict(data.get("relationship_state") or {}),
            open_threads=list(data.get("open_threads") or []),
            recent_summary=str(data.get("recent_summary") or ""),
            retrieved_memories=list(data.get("retrieved_memories") or []),
            retrieved_worldbook_entries=list(data.get("retrieved_worldbook_entries") or []),
            subagent_advice=list(data.get("subagent_advice") or []),
            routing_trace=dict(data.get("routing_trace") or {}),
        )
