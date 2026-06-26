"""Sub-agent orchestrator (Phase 1).

Consumes ``RoundRoutingDecision.subagent_jobs`` and runs each via the existing
``delegate_tool._run_sub_agent`` engine, wrapped with a timeout and full
exception capture. All failures are fail-open: the writer always proceeds,
with or without advice.

Design constraints (per V1 plan):
- Default max concurrency 1; high-complexity 2; at most 2 jobs/turn.
- Each sub-agent receives minimal context (scene + relevant memories + input
  summary) — never full history or the main writer's narrative.
- Sub-agent raw output is never shown to the player; only a compact ``advice``
  string is passed into the writer's internal context.
- Timeouts and exceptions are caught and recorded, never raised.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Callable, Optional

from .round_contracts import SubAgentJob, SubAgentResult


# Default budget — Phase 1 keeps cost/latency low for a personal project.
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_CONCURRENCY = 1
HIGH_COMPLEXITY_MAX_CONCURRENCY = 2
MAX_JOBS_PER_TURN = 2


def _build_minimal_context(
    job: SubAgentJob,
    *,
    scene_state: dict[str, Any],
    relationship_state: dict[str, Any],
    open_threads: list[dict[str, Any]],
    relevant_memories: list[dict[str, Any]],
    user_input: str,
    recent_summary: str,
) -> str:
    """Build the minimal context string for a sub-agent.

    Deliberately excludes full chat history and the writer's draft. Sub-agents
    reason over scene + state + a few memories + the player input only.
    """
    parts: list[str] = []
    if scene_state:
        parts.append(f"## Scene\n{scene_state}")
    if relationship_state:
        parts.append(f"## Relationship State\n{relationship_state}")
    if open_threads:
        threads_text = "; ".join(
            str(t.get("subject") or t.get("summary") or t) for t in open_threads[:5]
        )
        parts.append(f"## Open Threads\n{threads_text}")
    if relevant_memories:
        mem_text = "\n".join(
            f"- {m.get('title') or m.get('content', '')[:80]}"
            for m in relevant_memories[:5]
        )
        parts.append(f"## Relevant Memories\n{mem_text}")
    if recent_summary:
        parts.append(f"## Recent Summary\n{recent_summary[:400]}")
    parts.append(f"## Player Input\n{user_input[:600]}")
    return "\n\n".join(parts)


class SubAgentOrchestrator:
    """Runs sub-agent jobs with timeout + fail-open semantics."""

    def __init__(
        self,
        run_fn: Optional[Callable[..., str]] = None,
        *,
        default_timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # Lazily import to avoid pulling LLM deps at module import time.
        if run_fn is None:
            from ..tools.builtin.delegate_tool import _run_sub_agent
            run_fn = _run_sub_agent
        self._run_fn = run_fn
        self._default_timeout = default_timeout

    def run_jobs(
        self,
        jobs: list[SubAgentJob],
        *,
        scene_state: Optional[dict[str, Any]] = None,
        relationship_state: Optional[dict[str, Any]] = None,
        open_threads: Optional[list[dict[str, Any]]] = None,
        relevant_memories: Optional[list[dict[str, Any]]] = None,
        user_input: str = "",
        recent_summary: str = "",
        max_concurrency: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ) -> list[SubAgentResult]:
        """Run sub-agent jobs, returning one result per job (fail-open).

        Args:
            jobs: Jobs from the routing decision (capped to MAX_JOBS_PER_TURN).
            max_concurrency: Override; defaults based on job count/priority.
            timeout_seconds: Per-job timeout override.
        """
        jobs = list(jobs)[:MAX_JOBS_PER_TURN]
        if not jobs:
            return []

        scene_state = scene_state or {}
        relationship_state = relationship_state or {}
        open_threads = open_threads or []
        relevant_memories = relevant_memories or []

        if max_concurrency is None:
            max_concurrency = (
                HIGH_COMPLEXITY_MAX_CONCURRENCY
                if (len(jobs) >= 2 or any(j.priority == "high" for j in jobs))
                else DEFAULT_MAX_CONCURRENCY
            )

        def _run_one(job: SubAgentJob) -> SubAgentResult:
            start = time.time()
            timeout = timeout_seconds or self._default_timeout
            ctx = _build_minimal_context(
                job,
                scene_state=scene_state,
                relationship_state=relationship_state,
                open_threads=open_threads,
                relevant_memories=relevant_memories,
                user_input=user_input,
                recent_summary=recent_summary,
            )
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(
                        self._run_fn,
                        profile_id=job.profile,
                        task=job.task,
                        context=ctx,
                        max_iterations=2,
                    )
                    raw = future.result(timeout=timeout)
                # _run_sub_agent returns error strings (e.g. "Error: profile
                # 'x' not found", "Sub-agent LLM error: ...") instead of
                # raising. Detect these so fail-open records ok=False and does
                # not pass the error text into the writer as "advice".
                _err = self._detect_error(raw)
                if _err:
                    return SubAgentResult(
                        profile=job.profile,
                        task_type=job.task_type,
                        ok=False,
                        error=_err,
                        elapsed_ms=int((time.time() - start) * 1000),
                    )
                advice = self._compact_advice(raw)
                return SubAgentResult(
                    profile=job.profile,
                    task_type=job.task_type,
                    ok=True,
                    advice=advice,
                    elapsed_ms=int((time.time() - start) * 1000),
                )
            except concurrent.futures.TimeoutError:
                return SubAgentResult(
                    profile=job.profile,
                    task_type=job.task_type,
                    ok=False,
                    error=f"timeout after {timeout}s",
                    elapsed_ms=int((time.time() - start) * 1000),
                )
            except Exception as exc:  # noqa: BLE001 — fail-open, never raise
                return SubAgentResult(
                    profile=job.profile,
                    task_type=job.task_type,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_ms=int((time.time() - start) * 1000),
                )

        if max_concurrency >= len(jobs) and len(jobs) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as ex:
                results = list(ex.map(_run_one, jobs))
        else:
            results = [_run_one(j) for j in jobs]
        return results

    @staticmethod
    def _detect_error(raw: str) -> str:
        """Return the error message if ``raw`` is an _run_sub_agent error string."""
        raw = str(raw or "")
        for prefix in ("Error: profile ", "Sub-agent LLM error", "Sub-agent reached max iterations"):
            if raw.startswith(prefix):
                return raw[:200]
        return ""

    @staticmethod
    def _compact_advice(raw: str, max_chars: int = 1200) -> str:
        """Compact sub-agent raw output to a bounded advice string.

        Never the full raw output; never exposed to the player verbatim.
        """
        raw = str(raw or "")
        # Collapse excessive whitespace, bound length.
        compact = " ".join(raw.split())
        if len(compact) > max_chars:
            compact = compact[:max_chars].rstrip() + "…"
        return compact

    @staticmethod
    def advice_to_packet_field(results: list[SubAgentResult]) -> list[dict[str, Any]]:
        """Convert results into the ``subagent_advice`` packet field."""
        return [
            {
                "profile": r.profile,
                "task_type": r.task_type,
                "ok": r.ok,
                "advice": r.advice,
                "error": r.error,
            }
            for r in results
        ]
