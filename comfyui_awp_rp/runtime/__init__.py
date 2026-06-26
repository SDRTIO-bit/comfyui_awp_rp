"""AWP RP runtime — deterministic round orchestration layer (V1).

This package hosts the Phase 1 routing/orchestration/sanitization modules.
They are intentionally framework-agnostic (no ComfyUI dependency) so they
can be unit-tested in isolation.
"""

from .round_contracts import (
    RoundRoutingDecision,
    SubAgentJob,
    SubAgentResult,
    RoundContextPacket,
)
from .round_routing import build_round_routing_decision
from .output_sanitizer import sanitize_output, SanitizerAction, SanitizerVerdict
from .subagent_orchestrator import SubAgentOrchestrator

__all__ = [
    "RoundRoutingDecision",
    "SubAgentJob",
    "SubAgentResult",
    "RoundContextPacket",
    "build_round_routing_decision",
    "sanitize_output",
    "SanitizerAction",
    "SanitizerVerdict",
    "SubAgentOrchestrator",
]
