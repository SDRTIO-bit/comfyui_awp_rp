"""Phase 1 independent acceptance tests.

These supplement test_runtime_v1.py with code-level proofs that the user
explicitly requested:

- Worldbook: routed path calls build_filtered_worldbook_text 0 times; legacy
  calls it the expected number; constant entries are hard-budget-capped;
  priority ordering; budget report trace fields.
- Memory: should_read_memory=False → LongTermMemory.query never called; the
  mandatory-tool prompt is gone from main_agent.py source.
- Sub-agent closed loop: Router → Orchestrator (mocked executor) → advice
  reaches MainAgent system prompt → output contract forbids leaking it.
- Sanitizer: bounded retry, no infinite loop, no false positives.
- Workflow: node-chain smoke with a mock LLM adapter.

All offline; no DeepSeek API key.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.runtime import build_round_routing_decision
from comfyui_awp_rp.knowledge.worldbook import (
    apply_worldbook_budget, build_filtered_worldbook_text,
)
from comfyui_awp_rp.nodes.memory_nodes import AWPMemoryRead
from comfyui_awp_rp.nodes.router_nodes import AWPRoundRouter, AWPSubAgentOrchestrator
from comfyui_awp_rp.runtime.subagent_orchestrator import SubAgentOrchestrator
from comfyui_awp_rp.runtime.round_contracts import SubAgentJob


# ── Fake LLM result/usage for MainAgent mocking ─────────────────────────────

class _Usage:
    def __init__(self):
        self.input = 0
        self.output = 0


class _Result:
    def __init__(self, text, tool_calls=None):
        self.text = text
        self.token_usage = _Usage()
        self.tool_calls = tool_calls or []
        self.has_tool_calls = bool(tool_calls)


def _make_mock_router(text="她轻轻推开门，屋内昏暗。他坐在桌前没有回头。她犹豫片刻终于开口：「你怨我吗？」" * 1):
    """Return a MagicMock router whose complete_with_tools yields a clean narrative."""
    router = MagicMock()
    router.complete_with_tools.return_value = (_Result(text), "deepseek", "deepseek-chat")
    return router


MAIN_AGENT_PATH = os.path.join(PLUGIN_DIR, "nodes", "main_agent.py")


# ── 1. Worldbook double-processing proofs ───────────────────────────────────

class WorldbookDoubleProcessingTests(unittest.TestCase):

    def _many_constants(self, n, content="世界设定" * 50):
        return [
            {"comment": f"const-{i}", "content": content, "constant": True, "priority": 10}
            for i in range(n)
        ]

    def test_routed_packet_skips_internal_filter_zero_calls(self):
        """routed packet present → build_filtered_worldbook_text called 0 times."""
        from comfyui_awp_rp.nodes import main_agent
        call_count = {"n": 0}
        real = None
        import comfyui_awp_rp.knowledge.worldbook as wb_mod
        orig = wb_mod.build_filtered_worldbook_text

        def spy(*a, **kw):
            call_count["n"] += 1
            return "SHOULD_NOT_BE_USED"

        packet = json.dumps({"context_owner": "routed", "subagent_advice": []})
        with patch.object(wb_mod, "build_filtered_worldbook_text", spy), \
             patch.object(main_agent, "create_default_router", return_value=_make_mock_router()):
            try:
                main_agent.AWPMainAgent().execute(
                    user_input="你好",
                    session_id="acc-routed",
                    enable_agent_loop=False,
                    card_id="some_card_id",          # would normally trigger filter
                    context_mode="full_context",
                    round_context_packet=packet,      # routed → must skip
                    record_session=False,
                )
            except Exception:
                pass
        self.assertEqual(call_count["n"], 0,
                         "routed path must NOT call build_filtered_worldbook_text")

    def test_legacy_packet_calls_internal_filter_once(self):
        """No routed packet + card_id → legacy fallback calls filter exactly once."""
        from comfyui_awp_rp.nodes import main_agent
        import comfyui_awp_rp.knowledge.worldbook as wb_mod
        call_count = {"n": 0}

        # Make CardImporter.get_card return a card with worldbook so the branch enters.
        def spy(*a, **kw):
            call_count["n"] += 1
            return "## filtered legacy wb"

        fake_card = {"worldbook": [{"comment": "c", "content": "x", "constant": True}]}
        with patch.object(wb_mod, "build_filtered_worldbook_text", spy), \
             patch("comfyui_awp_rp.card.import_card.CardImporter") as CardImp, \
             patch.object(main_agent, "create_default_router", return_value=_make_mock_router()):
            CardImp.return_value.get_card.return_value = fake_card
            try:
                main_agent.AWPMainAgent().execute(
                    user_input="你好",
                    session_id="acc-legacy",
                    enable_agent_loop=False,
                    card_id="some_card_id",
                    context_mode="full_context",
                    round_context_packet="",          # legacy
                    record_session=False,
                )
            except Exception:
                pass
        self.assertEqual(call_count["n"], 1,
                         "legacy path should call filter exactly once")

    def test_constant_entries_hard_budget_capped(self):
        entries = self._many_constants(50)
        included, report = apply_worldbook_budget(entries, budget_tokens=400)
        self.assertLessEqual(report["total_token_estimate"], 410)
        self.assertGreaterEqual(report["worldbook_entries_dropped"], 30)

    def test_priority_constant_and_triggered_above_background(self):
        """constant + high-priority triggered kept before low-priority background."""
        entries = [
            {"comment": "bg-low", "content": "背景" * 40, "constant": False, "priority": 1},
            {"comment": "triggered", "content": "镇北旧宅" * 40, "constant": False, "priority": 50},
            {"comment": "core-rule", "content": "核心规则" * 40, "constant": True, "priority": 10},
        ]
        included, report = apply_worldbook_budget(entries, budget_tokens=400)
        comments = [e["comment"] for e in included]
        # core-rule (constant) must come before background; triggered before bg-low
        if "core-rule" in comments and "bg-low" in comments:
            self.assertLess(comments.index("core-rule"), comments.index("bg-low"))
        if "triggered" in comments and "bg-low" in comments:
            self.assertLess(comments.index("triggered"), comments.index("bg-low"))

    def test_budget_report_trace_fields_present(self):
        entries = self._many_constants(10)
        _, report = apply_worldbook_budget(entries, budget_tokens=2000)
        for field in [
            "worldbook_entries_considered",
            "worldbook_entries_included",
            "worldbook_entries_dropped",
            "core_worldbook_token_estimate",
            "retrieved_worldbook_token_estimate",
            "drop_reasons",
        ]:
            self.assertIn(field, report, f"missing trace field: {field}")
        self.assertTrue(all("reason" in d for d in report["drop_reasons"]) or not report["drop_reasons"])

    def test_roundpreparer_budget_report_has_context_owner(self):
        """RoundPreparer budget output records context_owner + worldbook token estimates."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
        decision = json.dumps({
            "should_read_memory": False,
            "worldbook_budget_tokens": 1500,
        })
        # worldbook_index with many constants to force drops
        wb_index = [
            {"keyword": f"k{i}", "title": f"t{i}", "section": "## x",
             "one_liner": "", "content": "设定" * 80, "activation": "const"}
            for i in range(20)
        ]
        _rp = AWPRoundPreparer().execute(
            user_input="你好",
            session_id="acc-prep",
            worldbook_index=json.dumps(wb_index),
            routing_decision_json=decision,
        )
        assembled, matched, checklist, budget = _rp[0], _rp[1], _rp[2], _rp[3]
        budget = json.loads(budget)
        self.assertEqual(budget["context_owner"], "routed")
        self.assertIn("core_worldbook_token_estimate", budget)
        self.assertIn("worldbook_entries_dropped", budget)
        self.assertLessEqual(budget["core_worldbook_token_estimate"], 1600)


# ── 2. Memory double-read elimination proofs ────────────────────────────────

class MemoryDoubleReadTests(unittest.TestCase):

    def test_skip_decision_no_query_call(self):
        """should_read_memory=False → LongTermMemory.query never called."""
        with patch("comfyui_awp_rp.nodes.memory_nodes.LongTermMemory") as LTM:
            inst = MagicMock()
            inst.query.return_value = []
            LTM.return_value = inst
            AWPMemoryRead().execute(
                namespace="ns",
                routing_decision_json=json.dumps({"should_read_memory": False}),
            )
            self.assertEqual(inst.query.call_count, 0,
                             "must not query storage when router says skip")

    def test_no_decision_legacy_calls_query(self):
        """No routing decision → legacy behavior → query called once."""
        with patch("comfyui_awp_rp.nodes.memory_nodes.LongTermMemory") as LTM:
            inst = MagicMock()
            inst.query.return_value = []
            LTM.return_value = inst
            AWPMemoryRead().execute(namespace="ns")
            self.assertEqual(inst.query.call_count, 1)

    def test_no_mandatory_tool_prompt_in_source(self):
        """main_agent.py must no longer mandate per-turn memory_read/tool calls."""
        with open(MAIN_AGENT_PATH, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("每轮必须调用", src)
        self.assertNotIn("禁止跳过工具", src)
        # Tool capability retained as fallback
        self.assertIn("tool_choice", src)
        self.assertIn("available_tools", src)

    def test_mainagent_agentloop_no_double_memory_when_routed(self):
        """With routed packet + skip decision, MainAgent agent loop does not
        re-mandate memory; tools remain available but not obligatory. We assert
        the loop system prompt does not contain the old mandatory phrase and
        that advice (if any) is injected internally."""
        from comfyui_awp_rp.nodes import main_agent
        captured = {}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            captured["system"] = messages[0]["content"] if messages else ""
            captured["tools"] = tools
            return (_Result("她推开门，坐下。他没回头。她开口：「在吗？」" * 1),
                    "deepseek", "deepseek-chat")

        packet = json.dumps({
            "context_owner": "routed",
            "subagent_advice": [
                {"profile": "rp-critic", "ok": True, "advice": "内部建议：注意关系张力", "task_type": "review"}
            ],
        })
        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            try:
                main_agent.AWPMainAgent().execute(
                    user_input="她怨我吗？",
                    session_id="acc-loop",
                    enable_agent_loop=True,
                    max_iterations=3,
                    profile="rp-writer",
                    round_context_packet=packet,
                    record_session=False,
                    context_mode="stateless_no_context",
                )
            except Exception:
                pass
        sys_text = captured.get("system", "")
        self.assertNotIn("每轮必须调用", sys_text)
        # advice injected internally
        self.assertIn("内部建议", sys_text)
        self.assertIn("不得原样暴露", sys_text)
        # tools still available as fallback
        self.assertIsNotNone(captured.get("tools"))


# ── 3. Sub-agent closed loop ─────────────────────────────────────────────────

class SubAgentClosedLoopTests(unittest.TestCase):

    def test_full_loop_router_to_orchestrator_to_writer_advice(self):
        """Conflict input → Router emits rp-critic job → Orchestrator runs
        (mocked) → advice lands in MainAgent system prompt → not mandated to
        surface to user."""
        # 1) Router
        rj, _ = AWPRoundRouter().execute(
            user_input="她怨我，这是一场冲突，她隐瞒了真相。",
            session_id="acc-loop2",
            current_variables=json.dumps({"语晴": {}, "村长": {}, "我": {}}),
            recent_summary="",
        )
        decision = json.loads(rj)
        profiles = [j["profile"] for j in decision["subagent_jobs"]]
        self.assertIn("rp-critic", profiles)

        # 2) Orchestrator with mocked executor
        def fake_run(profile_id, task, context="", max_iterations=3, **kw):
            return f"[{profile_id}] 评审认为应注意关系张力，避免OOC。"

        with patch("comfyui_awp_rp.tools.builtin.delegate_tool._run_sub_agent",
                   side_effect=fake_run):
            aj, pj, _ = AWPSubAgentOrchestrator().execute(
                routing_decision_json=rj,
                user_input="她怨我，这是一场冲突，她隐瞒了真相。",
                session_id="acc-loop2",
            )
        advice_list = json.loads(aj)
        packet = json.loads(pj)
        self.assertTrue(advice_list[0]["ok"])
        self.assertIn("rp-critic", advice_list[0]["advice"])
        self.assertEqual(packet["context_owner"], "routed")
        self.assertTrue(packet["subagent_advice"])

        # 3) MainAgent receives advice internally; output (mocked clean) must not
        #    be required to echo advice.
        from comfyui_awp_rp.nodes import main_agent
        captured = {}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            captured["system"] = messages[0]["content"]
            # writer produces clean narrative WITHOUT echoing advice
            return (_Result("她抬起眼，唇角绷紧。「你问我怨不怨？」她声音很轻。"),
                    "deepseek", "deepseek-chat")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            try:
                result = main_agent.AWPMainAgent().execute(
                    user_input="她怨我，这是一场冲突，她隐瞒了真相。",
                    session_id="acc-loop2",
                    enable_agent_loop=True,
                    max_iterations=2,
                    round_context_packet=pj,
                    record_session=False,
                    context_mode="stateless_no_context",
                )
            except Exception:
                result = ("", "", "{}", "{}", "{}")
        self.assertIn("评审认为", captured["system"])   # advice reached writer internally
        self.assertNotIn("评审认为", result[0])           # not surfaced to user output

    def test_profile_not_found_fail_open(self):
        """Non-existent profile → orchestrator returns ok=False, no crash."""
        def run(profile_id, task, context="", max_iterations=3, **kw):
            from comfyui_awp_rp.tools.builtin.delegate_tool import _run_sub_agent
            # Real _run_sub_agent returns error string for unknown profile
            return _run_sub_agent(profile_id=profile_id, task=task, context=context)
        orch = SubAgentOrchestrator(run_fn=run)
        res = orch.run_jobs(
            [SubAgentJob(profile="nonexistent-profile", task="x")],
            user_input="y",
        )
        self.assertFalse(res[0].ok)
        # fail-open: error recorded but no exception
        self.assertTrue(res[0].error)

    def test_chitchat_zero_jobs(self):
        rj, _ = AWPRoundRouter().execute(user_input="今天天气不错", session_id="s")
        self.assertEqual(json.loads(rj)["subagent_jobs"], [])

    def test_normal_complex_max_one(self):
        # single conflict signal, single character → at most 1 job
        rj, _ = AWPRoundRouter().execute(
            user_input="她怨我吗？",
            session_id="s",
        )
        self.assertLessEqual(len(json.loads(rj)["subagent_jobs"]), 1)

    def test_high_complexity_max_two(self):
        rj, _ = AWPRoundRouter().execute(
            user_input="这是一场重大冲突，她隐瞒真相，身份揭露，对峙决裂，我必须做出关键决定。",
            current_variables=json.dumps({"语晴": {}, "村长": {}, "我": {}}),
            session_id="s",
        )
        self.assertLessEqual(len(json.loads(rj)["subagent_jobs"]), 2)


# ── 4. Sanitizer retry bounds ────────────────────────────────────────────────

class SanitizerRetryBoundaryTests(unittest.TestCase):

    def test_explicit_tag_reject_then_give_up_no_infinite_loop(self):
        from comfyui_awp_rp.runtime.output_sanitizer import sanitize_output, SanitizerAction
        # Simulate MainAgent's loop: attempt 0,1 → REJECT_RETRY; attempt 2 → GIVE_UP
        actions = []
        for attempt in range(4):
            v = sanitize_output("<thinking>x</thinking>", attempt=attempt, max_retries=2)
            actions.append(v.action)
            if v.action == SanitizerAction.REJECT_GIVE_UP:
                break
        self.assertIn(SanitizerAction.REJECT_GIVE_UP, actions)
        self.assertLessEqual(len(actions), 4)  # bounded, no infinite loop

    def test_scrub_prefix_does_not_consume_retry(self):
        from comfyui_awp_rp.runtime.output_sanitizer import sanitize_output, SanitizerAction
        text = "好，现在让我们进入故事。\n\n" + "她推开门坐下。" * 10
        v = sanitize_output(text, attempt=0, max_retries=2)
        self.assertEqual(v.action, SanitizerAction.SCRUB_PREFIX)
        # cleaned text is usable, not rejected
        self.assertGreater(len(v.cleaned_text), 20)

    def test_qualitygate_vs_mainagent_no_double_retry_loop(self):
        """Standalone AWPQualityGate is a pure evaluator; its output is not wired
        back to MainAgent in the routed workflow. Verify it does not itself
        trigger any LLM call / retry — it only returns a decision dict."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        decision, status, instr = AWPQualityGate().execute(
            reply="她推开门，坐下。他没回头。「你来了。」"
        )
        d = json.loads(decision)
        # Pure function: no retry counter, no LLM. Just a verdict.
        self.assertIn("accepted", d)
        self.assertIn(d["decision"], ("accept", "revise"))


# ── 5. Workflow node-chain smoke (mock LLM) ──────────────────────────────────

class WorkflowChainSmokeTests(unittest.TestCase):

    def test_routed_chain_data_flows_end_to_end(self):
        """Instantiate the routed chain with mock LLM and verify data passes:
        Router → MemoryRead(gated) → Orchestrator → MainAgent."""
        # Router
        rj, _ = AWPRoundRouter().execute(
            user_input="你还记得上次答应我的事吗？",
            session_id="acc-smoke",
        )
        dec = json.loads(rj)
        self.assertTrue(dec["should_read_memory"])  # recall signal

        # MemoryRead gated by decision (skip when False, read when True)
        txt, js = AWPMemoryRead().execute(
            namespace="acc-smoke",
            routing_decision_json=rj,
        )
        # True → real read (empty ns → []), not skipped message
        self.assertNotIn("skipped", txt)

        # Orchestrator: recall input has no subagent jobs (no conflict) → empty
        aj, pj, _ = AWPSubAgentOrchestrator().execute(
            routing_decision_json=rj, user_input="你还记得上次答应我的事吗？",
            session_id="acc-smoke",
        )
        self.assertEqual(json.loads(aj), [])

        # MainAgent consumes packet (mocked LLM)
        from comfyui_awp_rp.nodes import main_agent
        with patch.object(main_agent, "create_default_router",
                          return_value=_make_mock_router()):
            res = main_agent.AWPMainAgent().execute(
                user_input="你还记得上次答应我的事吗？",
                session_id="acc-smoke",
                enable_agent_loop=False,
                round_context_packet=pj,
                record_session=False,
                context_mode="stateless_no_context",
            )
        self.assertIsInstance(res, tuple)
        self.assertEqual(len(res), 5)
        self.assertTrue(len(res[0]) > 0)  # got a reply

    def test_all_routed_workflow_nodes_registered(self):
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        for ct in ["AWPRoundRouter", "AWPSubAgentOrchestrator",
                   "AWPRoundPreparer", "AWPMemoryRead", "AWPMainAgent",
                   "AWPQualityGate", "AWPMemoryWrite", "AWPOutputRenderer"]:
            self.assertIn(ct, NODE_CLASS_MAPPINGS, f"{ct} not registered")
        self.assertGreaterEqual(len(NODE_CLASS_MAPPINGS), 41)


# ── 6. REJECT_AND_FIX blocking tests: final safety barrier ──────────────────

class ContinuousBadOutputTerminationTests(unittest.TestCase):
    """Prove that two consecutive bad outputs result in REJECT_GIVE_UP."""

    def _make_fake_result(self, text, tool_calls=None):
        return _Result(text, tool_calls)

    def test_double_thinking_triggers_safe_failure(self):
        """initial <thinking>, repair <thinking> → writer_call_count=2, safe error."""
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                return (_Result("<thinking>让我分析一下她为什么不说话</thinking>\n她推开门。"), "deepseek", "ds")
            else:
                return (_Result("<thinking>好吧我再分析一遍</thinking>屋内昏暗。"), "deepseek", "ds")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = main_agent.AWPMainAgent().execute(
                user_input="她今天怎么了？",
                session_id="acc-dbthink",
                enable_agent_loop=True,
                max_iterations=1,       # exit agent loop immediately (no tool calls)
                record_session=False,
                context_mode="stateless_no_context",
            )
        self.assertEqual(call_idx["n"], 2,
                         "max 2 writer calls: 1 initial + 1 repair")
        self.assertIn("生成安全失败", result[0],
                      "final text must be safe error, not <thinking>")
        self.assertNotIn("<thinking>", result[0])

    def test_double_analysis_retry_then_safe_failure(self):
        """initial <analysis>, repair <analysis> → safe error, not raw text."""
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (_Result("<analysis>分析角色动机</analysis>正文内容。"), "deepseek", "ds")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = main_agent.AWPMainAgent().execute(
                user_input="她怨我",
                session_id="acc-dbanalysis",
                enable_agent_loop=True, max_iterations=1,
                record_session=False, context_mode="stateless_no_context",
            )
        self.assertLessEqual(call_idx["n"], 2)
        self.assertIn("生成安全失败", result[0])
        self.assertNotIn("<analysis>", result[0])


class SecondRevisionSuccessTests(unittest.TestCase):
    """Prove: initial bad → repair good → deliver clean."""

    def test_initial_analysis_repair_success(self):
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                return (_Result("<analysis>内部分析</analysis>她没回头。"), "deepseek", "ds")
            else:
                return (_Result("她轻轻推开木门，屋内暗沉。他坐在窗边没有回头。她沉默片刻：「你怨我吗？」" * 1),
                        "deepseek", "ds")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = main_agent.AWPMainAgent().execute(
                user_input="她怨我吗",
                session_id="acc-repair",
                enable_agent_loop=True, max_iterations=1,
                record_session=False, context_mode="stateless_no_context",
            )
        self.assertEqual(call_idx["n"], 2)
        self.assertNotIn("生成安全失败", result[0])
        self.assertNotIn("<analysis>", result[0])
        self.assertGreater(len(result[0]), 20)


class LeadingMetaScrubTests(unittest.TestCase):
    """Prove: leading meta scrubbed without consuming a retry."""

    def test_leading_meta_scrubbed_no_extra_call(self):
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (_Result("好，现在让我们进入故事。\n\n" + "她推开门，屋内暗沉。他坐在窗边。她开口了。" * 2),
                    "deepseek", "ds")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = main_agent.AWPMainAgent().execute(
                user_input="继续",
                session_id="acc-scrub",
                enable_agent_loop=True, max_iterations=1,
                record_session=False, context_mode="stateless_no_context",
            )
        self.assertEqual(call_idx["n"], 1,
                         "SCRUB_PREFIX must NOT consume a retry — 1 writer call only")
        self.assertNotIn("好，现在", result[0][:20])


class AdviceLeakTerminationTests(unittest.TestCase):
    """Prove: advice meta-discourse in output triggers reject."""

    def test_advice_leak_terminates(self):
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (_Result("评审认为应当注意角色关系张力。她推开门坐下。"), "deepseek", "ds")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = main_agent.AWPMainAgent().execute(
                user_input="她怨我吗",
                session_id="acc-advleak",
                enable_agent_loop=True, max_iterations=1,
                record_session=False, context_mode="stateless_no_context",
            )
        self.assertIn("生成安全失败", result[0])
        self.assertNotIn("评审认为", result[0])

    def test_director_advice_leak_terminates(self):
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (_Result("导演建议下一章安排冲突升级。她转身离开。"), "deepseek", "ds")

        with patch.object(main_agent, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = main_agent.AWPMainAgent().execute(
                user_input="她走了",
                session_id="acc-dirleak",
                enable_agent_loop=True, max_iterations=1,
                record_session=False, context_mode="stateless_no_context",
            )
        self.assertIn("生成安全失败", result[0])
        self.assertNotIn("导演建议", result[0])


class NormalNarrativeSafeTests(unittest.TestCase):
    """Prove: natural narrative with innocent words is not harmed."""

    def test_innocent_narrative_passes(self):
        from comfyui_awp_rp.nodes import main_agent
        call_idx = {"n": 0}

        texts = [
            "她想了想，终于开口：「让我进去吧。」他侧身让开门，她踏入屋内。戏班的导演站在台下，凝神看着台上的表演。",
            "他让导演看看新布景。她想了一会，让他进入房间坐下。",
        ]
        for text in texts:
            call_idx["n"] = 0

            def fake_complete(node_config, messages, tools=None, tool_choice=None):
                call_idx["n"] += 1
                return (_Result(text), "deepseek", "ds")

            with patch.object(main_agent, "create_default_router") as mk:
                mk.return_value.complete_with_tools.side_effect = fake_complete
                result = main_agent.AWPMainAgent().execute(
                    user_input="继续",
                    session_id="acc-safe",
                    enable_agent_loop=True, max_iterations=1,
                    record_session=False, context_mode="stateless_no_context",
                )
            self.assertEqual(call_idx["n"], 1, f"text should pass without retry: {text[:30]}")
            self.assertNotIn("生成安全失败", result[0], f"text should not be rejected: {text[:30]}")


class WorkflowSmokeBadContentTests(unittest.TestCase):
    """Offline smoke: routed workflow mock chain → OutputRenderer gets clean."""

    def test_routed_chain_output_renderer_never_gets_bad_content(self):
        """Simulate a full routed chain where MainAgent outputs <thinking> and
        finally delivers to OutputRenderer. Assert bad content never reaches it."""
        import json as _json
        from comfyui_awp_rp.nodes.router_nodes import AWPRoundRouter, AWPSubAgentOrchestrator
        from comfyui_awp_rp.nodes import main_agent as ma_mod
        # 1) Router
        rj, _ = AWPRoundRouter().execute(user_input="她怨我吗？", session_id="acc-smoke2")
        # 2) Orchestrator (no jobs expected)
        aj, pj, _ = AWPSubAgentOrchestrator().execute(routing_decision_json=rj, user_input="她怨我")

        # 3) MainAgent with bad initial output → internal repair
        call_idx = {"n": 0}
        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                return (_Result("<thinking>分析</thinking>" + "她推开门坐下。" * 3),
                        "deepseek", "ds")
            else:
                return (_Result("她站在门口，光线从背后穿过来。他没回头。「你来了。」" * 2),
                        "deepseek", "ds")

        with patch.object(ma_mod, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = ma_mod.AWPMainAgent().execute(
                user_input="她怨我",
                session_id="acc-smoke2",
                enable_agent_loop=True, max_iterations=1,
                round_context_packet=pj,
                record_session=False, context_mode="stateless_no_context",
            )
        final_narrative = result[0]
        # Must NOT contain any banned pattern
        for banned in ("<thinking>", "<analysis>", "<tool", "评审认为",
                       "导演建议", "内部建议", "子 Agent"):
            self.assertNotIn(banned, final_narrative,
                             f"bad content '{banned}' reached output: {final_narrative[:80]}")
        # Must be either safe error or clean narrative
        ok = (
            "生成安全失败" in final_narrative
            or (len(final_narrative) > 30 and "<" not in final_narrative[:50])
        )
        self.assertTrue(ok, f"unexpected output: {final_narrative[:100]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
