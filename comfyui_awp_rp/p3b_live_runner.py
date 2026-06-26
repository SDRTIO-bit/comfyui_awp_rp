#!/usr/bin/env python
"""P3B: Interactive turn-by-turn live RP runner.  40 turns minimum.

Each turn is a separate invocation.  After seeing the AI reply you write the
next input and run again.  Nothing is scripted — the story evolves naturally.

Usage:
  python -m comfyui_awp_rp.p3b_live_runner --init                          # start new session
  python -m comfyui_awp_rp.p3b_live_runner --input "老马推开院门..."         # turn 1
  python -m comfyui_awp_rp.p3b_live_runner --input "她抬起眼..."             # turn 2
  ...
  python -m comfyui_awp_rp.p3b_live_runner --report                         # final report

State is persisted in artifacts/p3b_state.json.
Full conversation in artifacts/p3b_conversation.jsonl.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

ARTIFACT_DIR = os.path.join(PARENT_DIR, "artifacts")
STATE_PATH = os.path.join(ARTIFACT_DIR, "p3b_state.json")
CONV_PATH  = os.path.join(ARTIFACT_DIR, "p3b_conversation.jsonl")
REPORT_PATH = os.path.join(ARTIFACT_DIR, "p3b_report.json")
CARD_WB_PATH = os.path.join(
    PARENT_DIR, "data", "cards",
    "1efc516266b0f4bbd0614c4fb8367d750e1d3e112ac7cafe390bdb4e074ad8ac",
    "worldbook.json",
)

NOW_TS = lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ═══════════════════════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════════════════════

def _fresh_state() -> dict:
    return {
        "session_id": f"p3b-{uuid.uuid4().hex[:8]}",
        "turn_index": 0,
        "current_variables": "{}",
        "last_memory_read_turn": 0,
        "started_at": NOW_TS(),
        "live": True,
    }


def load_state() -> dict:
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH, encoding="utf-8"))
    return _fresh_state()


def save_state(s: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def load_worldbook() -> list[dict]:
    try:
        raw = json.load(open(CARD_WB_PATH, encoding="utf-8"))
        if not isinstance(raw, list):
            raw = raw.get("entries", [])
    except Exception:
        raw = []
    entries = []
    for e in raw:
        meta = e.get("metadata", {}) if isinstance(e.get("metadata"), dict) else {}
        title = str(e.get("title", ""))
        tags = list(e.get("tags", []))
        keys = meta.get("sourceKeys") or tags
        if isinstance(keys, str): keys = [keys]
        kw = (str(keys[0]) if keys else title) or f"e{len(entries)}"
        entries.append({
            "keyword": kw,
            "title": title or kw,
            "activation": "const" if meta.get("sourceConstant") else "selective",
            "priority": float(e.get("priority", 50) or 50),
            "one_liner": "",
            "content": str(e.get("content", "")),
            "section": str(e.get("content", "")) if meta.get("sourceConstant") else f"## {title or kw}",
        })
    return entries


# ═══════════════════════════════════════════════════════════════════════════
# Turn runner
# ═══════════════════════════════════════════════════════════════════════════

def run_turn(user_input: str):
    """Execute one live turn through the full routed pipeline."""
    state = load_state()
    state["turn_index"] += 1
    turn = state["turn_index"]
    save_state(state)  # commit turn number immediately

    wb = load_worldbook()
    core_kw = list({e["keyword"] for e in wb if e["activation"] == "const"})[:20]

    from comfyui_awp_rp.nodes.router_nodes import AWPRoundRouter, AWPSubAgentOrchestrator
    from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
    from comfyui_awp_rp.nodes import main_agent as ma_mod

    t0 = time.time()
    metrics: dict[str, Any] = {"turn": turn, "user_input": user_input[:80]}

    # ── 1) Router ──
    rj, rdbg = AWPRoundRouter().execute(
        user_input=user_input, session_id=state["session_id"],
        turn_index=turn,
        last_memory_read_turn=state["last_memory_read_turn"],
        current_variables=state["current_variables"],
        worldbook_core_keywords=",".join(core_kw),
        worldbook_budget_tokens=2500,
    )
    rdec = json.loads(rj)
    metrics["should_read_memory"] = rdec.get("should_read_memory", False)
    metrics["should_search_worldbook"] = rdec.get("should_search_worldbook", False)
    metrics["subagent_profiles"] = [j.get("profile", "") for j in rdec.get("subagent_jobs", [])]
    metrics["should_curate_memory"] = rdec.get("should_curate_memory", False)

    if rdec.get("should_read_memory"):
        state["last_memory_read_turn"] = turn

    # ── 2) RoundPreparer ──
    assembled, matched_wb, checklist, budget_str = AWPRoundPreparer().execute(
        user_input=user_input, session_id=state["session_id"],
        worldbook_index=json.dumps(wb, ensure_ascii=False),
        routing_decision_json=rj, top_worldbook=5,
    )
    budget = json.loads(budget_str) if isinstance(budget_str, str) else {}
    metrics.update({
        "wb_included": budget.get("worldbook_entries_included", 0),
        "wb_dropped": budget.get("worldbook_entries_dropped", 0),
        "wb_core_est": budget.get("core_worldbook_token_estimate", 0),
        "context_owner": budget.get("context_owner", "legacy"),
    })

    # ── 3) Orchestrator ──
    aj, pj, odbg = AWPSubAgentOrchestrator().execute(
        routing_decision_json=rj, user_input=user_input,
        session_id=state["session_id"],
        current_variables=state["current_variables"],
        retrieved_worldbook=matched_wb,
    )
    packet = json.loads(pj) if isinstance(pj, str) else {}
    odbg_dec = json.loads(odbg) if isinstance(odbg, str) else {}
    metrics["subagent_ok"] = len(odbg_dec.get("jobs_ok", []))
    metrics["subagent_failed"] = len(odbg_dec.get("jobs_failed", []))

    sm = packet.get("structured_memories", {}) if isinstance(packet, dict) else {}
    metrics["structured_facts_read"] = len(sm.get("story_facts", []))
    metrics["structured_threads_read"] = len(sm.get("open_threads", []))
    metrics["structured_scene_read"] = bool(sm.get("scene_state"))

    # ── 4) MainAgent (LIVE) ──
    try:
        res = ma_mod.AWPMainAgent().execute(
            user_input=user_input, session_id=state["session_id"],
            enable_agent_loop=True, max_iterations=2,
            round_context_packet=pj,
            record_session=False,
            context_mode="full_context",
            current_variables=state["current_variables"],
            card_id="",  # worldbook handled by RoundPreparer
        )
    except Exception as exc:
        print(f"\n[LIVE ERROR] {exc}")
        res = (f"[ERROR: {exc}]", "{}", "{}", "{}", "{}")

    final_text, session_ctx, meta_json, updated_vars, changes_json = res
    metrics["output_length"] = len(final_text or "")
    metrics["elapsed_ms"] = (time.time() - t0) * 1000

    try:
        meta = json.loads(meta_json) if isinstance(meta_json, str) else (meta_json or {})
    except Exception:
        meta = {}
    metrics["writer_call_count"] = meta.get("writer_call_count", 1)
    metrics["quality_gate_retries"] = meta.get("repair_retries_used", 0)
    metrics["sanitizer_actions"] = [s.get("action", "") for s in meta.get("sanitizer_log", [])]
    metrics["routed_context"] = meta.get("routed_context", False)
    curation = meta.get("memory_curation", {}) or {}
    metrics["curation_attempted"] = curation.get("triggered", False)
    metrics["curation_written"] = curation.get("written", 0)
    metrics["curation_error"] = curation.get("error", "")
    token_usage = meta.get("token_usage", {})

    # Update state
    state["current_variables"] = updated_vars

    # Append to conversation log
    log_entry = {
        "turn": turn, "user_input": user_input, "ai_reply": final_text,
        "metrics": metrics, "token_usage": token_usage,
        "timestamp": NOW_TS(),
    }
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(CONV_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    save_state(state)

    # ── Print Results ──
    bar = "-" * 72
    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
    print(f"\n{bar}")
    print(f"  TURN {turn}  |  {metrics['elapsed_ms']:.0f}ms  |  writer_calls={metrics['writer_call_count']}")
    print(f"  mem_read={metrics['should_read_memory']}  wb_search={metrics['should_search_worldbook']}(inc={metrics['wb_included']}/drop={metrics['wb_dropped']})")
    print(f"  sub_agents={metrics['subagent_profiles']}(ok={metrics['subagent_ok']}/fail={metrics['subagent_failed']})")
    print(f"  curate={metrics['should_curate_memory']}(w={metrics['curation_written']})  s_read={metrics['structured_facts_read']}f/{metrics['structured_threads_read']}t")
    print(f"  qgate_retry={metrics['quality_gate_retries']}  sanitizer={metrics['sanitizer_actions']}")
    print(f"  token_in={token_usage.get('input',0)}  token_out={token_usage.get('output',0)}")
    print(f"{bar}")
    try:
        print(final_text)
    except UnicodeEncodeError:
        print(final_text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    print(f"{bar}")

    # Safety checks
    warnings = []
    for tag in ("<thinking>", "<analysis>", "<tool>", "评审认为", "导演建议"):
        if tag in final_text:
            warnings.append(f"LEAK: {tag}")
    if metrics["writer_call_count"] > 2:
        warnings.append(f"WRITER_OVER: {metrics['writer_call_count']}")
    if warnings:
        print(f"  ⚠ WARNINGS: {' | '.join(warnings)}")
    print()

    return metrics


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

def generate_report():
    if not os.path.exists(CONV_PATH):
        print("No conversation data found.")
        return
    turns = []
    with open(CONV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                turns.append(json.loads(line))
    n = len(turns)
    all_m = [t["metrics"] for t in turns]
    all_tok = [t.get("token_usage", {}) for t in turns]

    report = {
        "mode": "live", "total_turns": n, "provider_called": True,
        "session_id": load_state().get("session_id", ""),
        "started_at": load_state().get("started_at", ""),
        "completed_at": NOW_TS(),
        "summary": {
            "memory_read_triggered": sum(1 for m in all_m if m.get("should_read_memory")),
            "worldbook_search_triggered": sum(1 for m in all_m if m.get("should_search_worldbook")),
            "subagent_jobs_ok": sum(m.get("subagent_ok", 0) for m in all_m),
            "subagent_jobs_failed": sum(m.get("subagent_failed", 0) for m in all_m),
            "curation_triggered": sum(1 for m in all_m if m.get("should_curate_memory")),
            "curation_written": sum(m.get("curation_written", 0) for m in all_m),
            "curation_errors": sum(1 for m in all_m if m.get("curation_error")),
            "structured_turns_with_data": sum(1 for m in all_m if m.get("structured_facts_read", 0) + m.get("structured_threads_read", 0) > 0),
            "quality_gate_retries": sum(m.get("quality_gate_retries", 0) for m in all_m),
            "sanitizer_actions": sum(len(m.get("sanitizer_actions", [])) for m in all_m),
            "avg_writer_calls": sum(m.get("writer_call_count", 1) for m in all_m) / n,
            "max_writer_calls": max(m.get("writer_call_count", 1) for m in all_m),
            "meta_leaks": sum(
                1 for t in turns
                if any(tag in t.get("ai_reply", "") for tag in
                       ("<thinking>", "<analysis>", "<tool>", "评审认为", "导演建议"))
            ),
            "total_token_input": sum(t.get("input", 0) for t in all_tok),
            "total_token_output": sum(t.get("output", 0) for t in all_tok),
            "avg_elapsed_ms": sum(m.get("elapsed_ms", 0) for m in all_m) / n,
            "routed_turns": sum(1 for m in all_m if m.get("context_owner") == "routed"),
        },
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"P3B LIVE Report — {n} turns")
    print(f"{'='*60}")
    for k, v in s.items():
        print(f"  {k}: {v}")
    print(f"\nReport: {REPORT_PATH}")

    return report


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="P3B live turn-by-turn RP runner")
    ap.add_argument("--init", action="store_true", help="Initialize new session")
    ap.add_argument("--input", type=str, default="", help="User input for this turn")
    ap.add_argument("--report", action="store_true", help="Generate final report")
    ap.add_argument("--status", action="store_true", help="Show current session status")
    args = ap.parse_args()

    if args.init:
        st = _fresh_state()
        save_state(st)
        # Clear conversation log
        if os.path.exists(CONV_PATH):
            os.remove(CONV_PATH)
        print(f"Session started: {st['session_id']}")
        print(f"Turn 0 — write your first input:")
        print(f"  python -m comfyui_awp_rp.p3b_live_runner --input \"...\"")
        sys.exit(0)

    if args.status:
        st = load_state()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        if os.path.exists(CONV_PATH):
            with open(CONV_PATH, "r", encoding="utf-8") as f:
                n = sum(1 for _ in f)
            print(f"Conversation turns: {n}")
        sys.exit(0)

    if args.report:
        generate_report()
        sys.exit(0)

    if not args.input.strip():
        print("Usage: --input \"your RP text\"  |  --init  |  --report  |  --status")
        sys.exit(1)

    run_turn(args.input.strip())
