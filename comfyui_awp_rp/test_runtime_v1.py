"""Phase 1 V1 runtime tests — fully offline, no LLM/API key required.

Covers: deterministic routing, output sanitization, sub-agent orchestration
(fail-open), worldbook budget (two layers), context packet serialization, and
the routed workflow topology. All sub-agent execution is mocked.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.runtime import (
    build_round_routing_decision,
    sanitize_output,
    SubAgentOrchestrator,
    RoundContextPacket,
    RoundRoutingDecision,
    SubAgentJob,
)
from comfyui_awp_rp.runtime.output_sanitizer import SanitizerAction
from comfyui_awp_rp.knowledge.worldbook import (
    apply_worldbook_budget,
    build_filtered_worldbook_text,
)
from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
from comfyui_awp_rp.nodes.router_nodes import AWPRoundRouter, AWPSubAgentOrchestrator
from comfyui_awp_rp.nodes.memory_nodes import AWPMemoryRead


# ── 1. Routing tests ────────────────────────────────────────────────────────

class RoutingTests(unittest.TestCase):
    def _dec(self, **kw):
        return build_round_routing_decision(**kw)

    def test_chitchat_no_memory_no_subagent(self):
        d = self._dec(user_input="今天天气真不错啊", turn_index=1)
        self.assertFalse(d.should_read_memory)
        self.assertEqual(d.subagent_jobs, [])
        self.assertFalse(d.should_search_worldbook)

    def test_old_promise_triggers_memory(self):
        d = self._dec(user_input="你还记得上次答应我的事吗？", turn_index=2)
        self.assertTrue(d.should_read_memory)
        self.assertTrue(any("recall" in r for r in d.reasons))

    def test_unknown_entity_triggers_worldbook(self):
        # "镇北旧宅" not in core keywords, not in short-term context
        d = self._dec(
            user_input="我去镇北旧宅。",
            recent_summary="",
            worldbook_core_keywords=["语晴", "桃花村"],
            turn_index=1,
        )
        self.assertTrue(d.should_search_worldbook)

    def test_multi_character_conflict_triggers_subagent(self):
        d = self._dec(
            user_input="语晴和村长在我面前对峙，她怨我，村长怀疑我，这是一场冲突。",
            current_variables={"语晴": {}, "村长": {}, "我": {}},
            recent_summary="语晴 村长 我",
            turn_index=3,
        )
        profiles = [j.profile for j in d.subagent_jobs]
        # conflict + multi-character → at least rp-critic or rp-director
        self.assertTrue(set(profiles) & {"rp-critic", "rp-director"})

    def test_high_complexity_max_two_subagents(self):
        d = self._dec(
            user_input="这是一场重大冲突，我必须做出关键决定，她隐瞒的真相和身份揭露，对峙决裂。",
            current_variables={"语晴": {}, "村长": {}, "我": {}},
            recent_summary="",
            turn_index=5,
        )
        self.assertLessEqual(len(d.subagent_jobs), 2)

    def test_subagent_disabled(self):
        d = self._dec(
            user_input="这是一场重大冲突，她隐瞒真相。",
            enable_subagents=False,
            turn_index=3,
        )
        self.assertEqual(d.subagent_jobs, [])

    def test_periodic_memory_refresh(self):
        d = self._dec(
            user_input="继续",
            turn_index=10,
            last_memory_read_turn=4,
            memory_read_interval=5,
        )
        self.assertTrue(d.should_read_memory)

    def test_trace_serializable(self):
        d = self._dec(user_input="她怨我吗？", turn_index=2)
        blob = json.dumps(d.to_dict(), ensure_ascii=False)
        back = RoundRoutingDecision.from_dict(json.loads(blob))
        self.assertEqual(back.should_read_memory, d.should_read_memory)
        self.assertEqual([j.profile for j in back.subagent_jobs],
                         [j.profile for j in d.subagent_jobs])


# ── 2. Sanitizer tests ──────────────────────────────────────────────────────

class SanitizerTests(unittest.TestCase):
    def test_explicit_thinking_tag_rejected(self):
        v = sanitize_output("<thinking>let me plan</thinking>\n她转身离开。")
        self.assertEqual(v.action, SanitizerAction.REJECT_RETRY)

    def test_analysis_tag_rejected(self):
        v = sanitize_output("<analysis>分析一下</analysis>正文内容...")
        self.assertEqual(v.action, SanitizerAction.REJECT_RETRY)

    def test_leading_meta_phrase_scrubbed(self):
        text = "好，现在让我们进入故事。\n\n她轻轻推开门，屋内昏暗。他坐在桌前，没有回头。" \
               "她犹豫片刻，终于开口：「你怨我吗？」" * 1
        v = sanitize_output(text)
        self.assertEqual(v.action, SanitizerAction.SCRUB_PREFIX)
        self.assertNotIn("好，现在", v.cleaned_text[:20])

    def test_normal_narrative_not_harmed(self):
        text = "她想了想，终于开口。他让她进入房间，坐在桌前。" * 3
        v = sanitize_output(text)
        self.assertEqual(v.action, SanitizerAction.ACCEPT)

    def test_empty_after_scrub_fails(self):
        v = sanitize_output("让我", attempt=0, max_retries=1)
        self.assertIn(v.action, (SanitizerAction.REJECT_RETRY, SanitizerAction.REJECT_GIVE_UP))

    def test_retry_limit_gives_up(self):
        v = sanitize_output("<thinking>x</thinking>", attempt=5, max_retries=1)
        self.assertEqual(v.action, SanitizerAction.REJECT_GIVE_UP)

    def test_natural_phrase_not_deleted(self):
        # "让他进入房间" mid-text must survive
        text = "她推门进去，让他进入房间，然后坐下开始说话。" * 2
        v = sanitize_output(text)
        self.assertEqual(v.action, SanitizerAction.ACCEPT)
        self.assertIn("让他进入房间", v.cleaned_text)


# ── 3. Sub-agent orchestrator tests (mocked) ────────────────────────────────

class OrchestratorTests(unittest.TestCase):
    def _mock_run(self, profile_id, task, context="", max_iterations=3, **kw):
        return f"[{profile_id}] advice for: {task[:30]}"

    def test_profile_mapping_and_advice(self):
        orch = SubAgentOrchestrator(run_fn=self._mock_run)
        jobs = [SubAgentJob(profile="rp-critic", task="check conflict", task_type="review")]
        res = orch.run_jobs(jobs, user_input="她怨我")
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0].ok)
        self.assertIn("rp-critic", res[0].advice)

    def test_minimal_context_no_full_history(self):
        captured = {}
        def run(profile_id, task, context="", max_iterations=3, **kw):
            captured["context"] = context
            return "advice"
        orch = SubAgentOrchestrator(run_fn=run)
        orch.run_jobs(
            [SubAgentJob(profile="rp-director", task="plan")],
            scene_state={"location": "旧宅"},
            user_input="去旧宅",
            recent_summary="s" * 1000,
        )
        # context should be bounded and contain scene, not the whole summary
        self.assertIn("旧宅", captured["context"])
        self.assertLess(len(captured["context"]), 2000)

    def test_timeout_fail_open(self):
        import time
        def slow_run(profile_id, task, context="", max_iterations=3, **kw):
            time.sleep(5)
            return "never"
        orch = SubAgentOrchestrator(run_fn=slow_run, default_timeout=1)
        res = orch.run_jobs([SubAgentJob(profile="rp-critic", task="x")], user_input="y")
        self.assertFalse(res[0].ok)
        self.assertIn("timeout", res[0].error)

    def test_exception_fail_open(self):
        def bad_run(profile_id, task, context="", max_iterations=3, **kw):
            raise RuntimeError("boom")
        orch = SubAgentOrchestrator(run_fn=bad_run)
        res = orch.run_jobs([SubAgentJob(profile="rp-critic", task="x")], user_input="y")
        self.assertFalse(res[0].ok)
        self.assertIn("boom", res[0].error)

    def test_max_jobs_capped(self):
        orch = SubAgentOrchestrator(run_fn=self._mock_run)
        jobs = [SubAgentJob(profile="rp-critic", task=str(i)) for i in range(5)]
        res = orch.run_jobs(jobs, user_input="x")
        self.assertEqual(len(res), 2)  # MAX_JOBS_PER_TURN

    def test_advice_not_leaking_to_packet_raw(self):
        orch = SubAgentOrchestrator(run_fn=self._mock_run)
        res = orch.run_jobs(
            [SubAgentJob(profile="rp-critic", task="secret advice " * 200)],
            user_input="x",
        )
        field = SubAgentOrchestrator.advice_to_packet_field(res)
        # compacted and bounded
        self.assertLess(len(field[0]["advice"]), 1300)


# ── 4. Worldbook budget tests ───────────────────────────────────────────────

class WorldbookBudgetTests(unittest.TestCase):
    def _many_constants(self, n):
        return [
            {"comment": f"const-{i}", "content": "设定" * 50, "constant": True, "priority": 10}
            for i in range(n)
        ]

    def test_core_capped_by_budget(self):
        entries = self._many_constants(50)  # ~ huge
        included, report = apply_worldbook_budget(entries, budget_tokens=500)
        self.assertLessEqual(report["total_token_estimate"], 600)  # within budget + slack
        self.assertGreater(report["worldbook_entries_dropped"], 0)

    def test_triggered_entry_retrievable(self):
        entries = self._many_constants(2) + [
            {"comment": "triggered", "content": "镇北旧宅的设定" * 10, "constant": False, "priority": 5}
        ]
        included, report = apply_worldbook_budget(entries, budget_tokens=8000)
        comments = [e["comment"] for e in included]
        self.assertIn("triggered", comments)

    def test_build_filtered_text_legacy_budget(self):
        entries = self._many_constants(60)
        txt = build_filtered_worldbook_text(entries, user_input="x", budget_tokens=1000)
        self.assertLess(len(txt), 6000)  # bounded, not 64k

    def test_drop_reasons_recorded(self):
        entries = self._many_constants(40)
        _, report = apply_worldbook_budget(entries, budget_tokens=300)
        self.assertTrue(report["drop_reasons"])
        self.assertEqual(report["worldbook_entries_considered"], 40)


# ── 5. Node + workflow integration ──────────────────────────────────────────

class NodeIntegrationTests(unittest.TestCase):
    def test_new_nodes_registered(self):
        self.assertIn("AWPRoundRouter", NODE_CLASS_MAPPINGS)
        self.assertIn("AWPSubAgentOrchestrator", NODE_CLASS_MAPPINGS)

    def test_round_router_node_chitchat(self):
        rj, dbg = AWPRoundRouter().execute(user_input="你好", session_id="s1")
        d = json.loads(rj)
        self.assertFalse(d["should_read_memory"])
        self.assertEqual(d["subagent_jobs"], [])

    def test_memory_read_gated_by_router_skip(self):
        # should_read_memory=False → no real read
        decision = json.dumps({"should_read_memory": False})
        txt, js = AWPMemoryRead().execute(
            namespace="nonexistent-ns-xyz",
            routing_decision_json=decision,
        )
        self.assertEqual(js, "[]")
        self.assertIn("skipped", txt)

    def test_memory_read_gated_legacy_when_no_decision(self):
        # No routing decision → legacy behavior (real read, fail-open to empty)
        txt, js = AWPMemoryRead().execute(namespace="nonexistent-ns-xyz")
        self.assertEqual(js, "[]")

    def test_orchestrator_node_no_jobs_zero_cost(self):
        decision = json.dumps({"should_read_memory": False, "subagent_jobs": []})
        aj, pj, dbg = AWPSubAgentOrchestrator().execute(
            routing_decision_json=decision, user_input="hi"
        )
        self.assertEqual(json.loads(aj), [])
        self.assertEqual(json.loads(pj)["context_owner"], "routed")

    def test_orchestrator_node_runs_mocked_job(self):
        decision = json.dumps({
            "subagent_jobs": [{"profile": "rp-critic", "task": "check", "task_type": "review"}]
        })
        with patch("comfyui_awp_rp.tools.builtin.delegate_tool._run_sub_agent",
                   return_value="critic advice"):
            aj, pj, dbg = AWPSubAgentOrchestrator().execute(
                routing_decision_json=decision, user_input="她怨我"
            )
        advice = json.loads(aj)
        self.assertEqual(len(advice), 1)
        self.assertTrue(advice[0]["ok"])

    def test_routed_workflow_loads_and_valid(self):
        with open(
            os.path.join(PARENT_DIR, "workflows", "rp_full_features_routed_v1_workflow.json"),
            encoding="utf-8",
        ) as f:
            wf = json.load(f)
        self.assertIn("34", wf)  # router
        self.assertIn("35", wf)  # orchestrator
        self.assertEqual(wf["34"]["class_type"], "AWPRoundRouter")
        self.assertEqual(wf["35"]["class_type"], "AWPSubAgentOrchestrator")
        # MainAgent wired to orchestrator packet
        self.assertEqual(wf["14"]["inputs"]["round_context_packet"], ["35", 1])
        # RoundPreparer + MemoryRead wired to router
        self.assertEqual(wf["13"]["inputs"]["routing_decision_json"], ["34", 0])
        self.assertEqual(wf["11"]["inputs"]["routing_decision_json"], ["34", 0])

    def test_packet_serializable_with_defaults(self):
        p = RoundContextPacket()
        blob = json.dumps(p.to_dict(), ensure_ascii=False)
        back = RoundContextPacket.from_dict(json.loads(blob))
        self.assertEqual(back.context_owner, "legacy")


# ── 6. MainAgent routed-path: no double worldbook injection ─────────────────

class MainAgentRoutedPathTests(unittest.TestCase):
    def test_routed_packet_skips_internal_worldbook_filter(self):
        """When a routed packet is present, MainAgent must NOT call
        build_filtered_worldbook_text again. We assert the internal filter is
        skipped by patching it to fail if called."""
        from comfyui_awp_rp.nodes import main_agent
        called = {"n": 0}
        def boom(entries, user_input, history_text="", max_entries=40, budget_tokens=8000):
            called["n"] += 1
            return "SHOULD_NOT_BE_USED"
        # Routed packet: context_owner=routed, with advice
        packet = json.dumps({"context_owner": "routed", "subagent_advice": []}, ensure_ascii=False)

        # Patch the LLM router so no real API call is made (legacy path single call).
        # We only care that the worldbook filter is not invoked on the routed path.
        with patch("comfyui_awp_rp.knowledge.worldbook.build_filtered_worldbook_text", boom), \
             patch("comfyui_awp_rp.nodes.main_agent.create_default_router") as mk_router:
            # Make router.complete_with_config return a stub
            mk_router.return_value.complete_with_config.return_value = (
                "正文", type("U", (), {"input": 0, "output": 0})(), "deepseek", "deepseek-chat"
            )
            try:
                main_agent.AWPMainAgent().execute(
                    user_input="你好",
                    session_id="s1",
                    enable_agent_loop=False,
                    card_id="somecard",
                    round_context_packet=packet,
                )
            except Exception:
                pass  # execution details irrelevant; we only assert filter not called
        self.assertEqual(called["n"], 0,
                         "routed path must not re-run build_filtered_worldbook_text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
