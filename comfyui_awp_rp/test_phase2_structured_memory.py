"""Phase 2 structured memory acceptance tests — all offline, no API key."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.memory.structured import (
    StructuredMemoryManager,
    StoryFact,
    OpenThread,
    SceneState,
    validate_story_fact,
    validate_open_thread,
    validate_scene_state,
)
from comfyui_awp_rp.runtime import build_round_routing_decision, RoundRoutingDecision
from comfyui_awp_rp.runtime.round_contracts import RoundContextPacket


import os as _os
import uuid as _uuid

def _new_mgr():
    """Return a fresh StructuredMemoryManager backed by a temp-file SQLite."""
    import tempfile
    from comfyui_awp_rp.core.store import SQLiteStore
    from comfyui_awp_rp.memory.long_term import LongTermMemory
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = SQLiteStore(tmp.name)
    return StructuredMemoryManager(store=store)


def _uniq(ns: str) -> str:
    """Unique namespace per test run to avoid cross-run pollution."""
    pid = _os.getpid()
    return f"{ns}-{pid}-{_uuid.uuid4().hex[:8]}"


# ── 1. Write and query tests ────────────────────────────────────────────────

class StructuredMemoryWriteAndQueryTests(unittest.TestCase):

    def test_write_story_fact_idempotent(self):
        mgr = _new_mgr()
        ns = "p2-idem"
        f = StoryFact(summary="玩家答应三日后前往镇北旧宅", entity_ids=["player", "语晴"],
                      confidence=0.8, importance=0.7, tags=["承诺"])
        r1, is_new1 = mgr.write_story_fact(ns, f)
        self.assertTrue(is_new1)
        # Second write of same fact — must update, not duplicate
        f2 = StoryFact(summary="玩家答应三日后前往镇北旧宅", entity_ids=["player", "语晴"],
                       confidence=0.9, importance=0.6, tags=["承诺", "关键"])
        r2, is_new2 = mgr.write_story_fact(ns, f2)
        self.assertFalse(is_new2)
        self.assertEqual(r1.id, r2.id)
        self.assertEqual(r2.metadata.get("confidence"), 0.9)  # max merged
        self.assertEqual(r2.importance, 0.7)                    # max merged
        self.assertIn("关键", r2.tags)

    def test_query_story_facts_by_entity(self):
        mgr = _new_mgr()
        ns = "p2-query"
        mgr.write_story_fact(ns, StoryFact(summary="秘密揭露", entity_ids=["语晴"]))
        mgr.write_story_fact(ns, StoryFact(summary="村长的债务", entity_ids=["村长"]))
        mgr.write_story_fact(ns, StoryFact(summary="共同约定", entity_ids=["语晴", "村长"]))
        r1 = mgr.query_story_facts(ns, entity_ids=["语晴"], limit=20)
        self.assertEqual(len(r1), 2)  # secret + joint
        r2 = mgr.query_story_facts(ns, entity_ids=["村长"], limit=20)
        self.assertEqual(len(r2), 2)  # debt + joint

    def test_write_open_thread_and_resolve(self):
        mgr = _new_mgr()
        ns = "p2-thread"
        t = OpenThread(topic="玉佩来源之谜", entity_ids=["语晴", "player"],
                       status="open", created_turn=3)
        r1, is_new = mgr.write_open_thread(ns, t)
        self.assertTrue(is_new)
        self.assertEqual(r1.metadata["status"], "open")
        # Resolve
        ok = mgr.resolve_thread(ns, t.thread_key, turn=8)
        self.assertTrue(ok)
        open_threads = mgr.query_open_threads(ns, status="open")
        self.assertEqual(open_threads, [])

    def test_write_scene_state_singleton(self):
        mgr = _new_mgr()
        ns = "p2-scene"
        s1 = SceneState(location="镇北旧宅", time_of_day="黄昏",
                        characters_present=["语晴", "player"])
        mgr.write_scene_state(ns, s1)
        got = mgr.get_scene_state(ns)
        self.assertEqual(got.location, "镇北旧宅")
        # Overwrite
        s2 = SceneState(location="桃花村", time_of_day="清晨")
        mgr.write_scene_state(ns, s2)
        got2 = mgr.get_scene_state(ns)
        self.assertEqual(got2.location, "桃花村")


# ── 2. Schema validation tests ──────────────────────────────────────────────

class SchemaValidationTests(unittest.TestCase):

    def test_valid_story_fact_passes(self):
        ok, err, f = validate_story_fact({
            "kind": "event", "summary": "她答应了三日之约",
            "entityIds": ["语晴"], "importance": 0.8,
        })
        self.assertTrue(ok)
        self.assertIsNotNone(f)

    def test_empty_entity_ids_rejected(self):
        ok, err, f = validate_story_fact({
            "kind": "event", "summary": "something", "entityIds": [],
        })
        self.assertFalse(ok)

    def test_unknown_kind_rejected(self):
        ok, err, f = validate_story_fact({
            "kind": "unknown-type", "summary": "x",
            "entityIds": ["a"],
        })
        self.assertFalse(ok)

    def test_valid_thread_passes(self):
        ok, err, t = validate_open_thread({
            "kind": "unresolved-thread", "summary": "谁杀了村长",
            "entityIds": ["player"],
        })
        self.assertTrue(ok)
        self.assertIsNotNone(t)

    def test_non_thread_kind_rejected(self):
        ok, err, t = validate_open_thread({
            "kind": "event", "summary": "x", "entityIds": ["a"],
        })
        self.assertFalse(ok)


# ── 3. Merge algorithm tests ───────────────────────────────────────────────

class MergeAlgorithmTests(unittest.TestCase):

    def test_fact_confidence_takes_max(self):
        mgr = _new_mgr()
        ns = "p2-merge"
        f1 = StoryFact(summary="事件A", entity_ids=["x"], confidence=0.6, importance=0.4)
        f2 = StoryFact(summary="事件A", entity_ids=["x"], confidence=0.9, importance=0.3)
        mgr.write_story_fact(ns, f1)
        r, _ = mgr.write_story_fact(ns, f2)
        self.assertEqual(r.metadata["confidence"], 0.9)
        self.assertEqual(r.importance, 0.4)  # max of 0.4 and 0.3

    def test_fact_key_normalizes_spacing(self):
        """same semantic content → same fact_key → no duplicate"""
        mgr = _new_mgr()
        ns = "p2-norm"
        f1 = StoryFact(summary="  她去  镇北旧宅  ", entity_ids=["语晴"])
        f2 = StoryFact(summary="她去 镇北旧宅", entity_ids=["语晴"])
        self.assertEqual(f1.fact_key, f2.fact_key)

    def test_thread_key_collision(self):
        t1 = OpenThread(topic="谁杀了村长", entity_ids=["语晴", "player"])
        t2 = OpenThread(topic="谁杀了村长", entity_ids=["player", "语晴"])  # order diff
        self.assertEqual(t1.thread_key, t2.thread_key)


# ── 4. Curator trigger routing tests ───────────────────────────────────────

class CuratorTriggerRoutingTests(unittest.TestCase):

    def test_conflict_triggers_curation(self):
        r = build_round_routing_decision("这是一场重大冲突，她隐瞒了真相。", turn_index=2)
        self.assertTrue(r.should_curate_memory)
        self.assertTrue(r.memory_curation_trigger)

    def test_chitchat_does_not_trigger(self):
        r = build_round_routing_decision("今天天气不错", turn_index=1)
        self.assertFalse(r.should_curate_memory)

    def test_scene_change_triggers(self):
        r = build_round_routing_decision("第二天，她离开村庄前往城里。", turn_index=4)
        self.assertTrue(r.should_curate_memory)

    def test_periodic_every_3_turns(self):
        r = build_round_routing_decision("嗯。", turn_index=6)
        self.assertTrue(r.should_curate_memory)
        self.assertIn("periodic", r.memory_curation_trigger)

    def test_routing_decision_serializes_curator_fields(self):
        r = build_round_routing_decision("她怨我，她隐瞒真相。", turn_index=3)
        d = json.loads(json.dumps(r.to_dict(), ensure_ascii=False))
        self.assertTrue(d["should_curate_memory"])
        self.assertTrue(d["memory_curation_trigger"])

    def test_v1_rules_unchanged_by_p2_additions(self):
        """V1 memory/worldbook/subagent decisions must be identical regardless
        of curator trigger — the new block is additive only."""
        # With and without curator-triggering signals
        r_signal = build_round_routing_decision("这是一场冲突，她隐瞒真相。", turn_index=2)
        r_plain = build_round_routing_decision("今天天气不错", turn_index=1)
        # Curator changes, but V1 fields must not be affected by curator changes
        self.assertTrue(r_signal.should_curate_memory)
        self.assertFalse(r_plain.should_curate_memory)
        # V1 memory trigger is independent
        self.assertTrue(r_signal.should_read_memory)  # recall signals in text

    def test_round_context_packet_backward_compat(self):
        """Old packets without curator fields must deserialize with defaults."""
        old = RoundContextPacket(context_owner="legacy")
        d = old.to_dict()
        # Simulate old data missing the new fields
        d.pop("should_curate_memory", None)
        d.pop("memory_curation_trigger", None)
        restored = RoundContextPacket.from_dict(d)
        self.assertFalse(restored.should_curate_memory)
        self.assertEqual(restored.memory_curation_trigger, "")


# ── 5. Curator pipeline mocked tests ────────────────────────────────────────

class CuratorPipelineMockedTests(unittest.TestCase):

    def test_ingest_facts_from_curator_output(self):
        mgr = _new_mgr()
        ns = "p2-ingest"
        candidates = [
            {"kind": "event", "summary": "她答应了约定", "entityIds": ["语晴"], "importance": 0.8},
            {"kind": "discovery", "summary": "玉佩来自旧宅", "entityIds": ["player"], "confidence": 0.9},
            {"kind": "unresolved-thread", "summary": "村长的外债真相", "entityIds": ["村长"]},
            # bad: missing entityIds
            {"kind": "event", "summary": "bad entry", "entityIds": []},
        ]
        stats = mgr.ingest_curator_candidates(ns, candidates, turn_index=5)
        self.assertEqual(stats["written"], 3)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["errors"][0], "[3] fact: empty entityIds")
        # Verify facts and threads were stored
        facts = mgr.query_story_facts(ns, limit=50)
        threads = mgr.query_open_threads(ns, limit=50)
        self.assertEqual(len(facts), 2)
        self.assertEqual(len(threads), 1)

    def test_ingest_duplicate_facts_updated_not_duplicated(self):
        mgr = _new_mgr()
        ns = "p2-dup"
        first = [{"kind": "event", "summary": "她去旧宅", "entityIds": ["语晴"], "importance": 0.6}]
        mgr.ingest_curator_candidates(ns, first, turn_index=1)
        second = [{"kind": "event", "summary": "她去旧宅", "entityIds": ["语晴"], "importance": 0.9}]
        stats = mgr.ingest_curator_candidates(ns, second, turn_index=2)
        self.assertEqual(stats["written"], 0)
        self.assertEqual(stats["updated"], 1)

    def test_curator_in_mainagent_fail_open(self):
        """curator LLM errors must never block MainAgent return."""
        from comfyui_awp_rp.nodes import main_agent as ma_mod
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (type("R", (), {
                "text": "她推开门，坐下。屋内暗沉。",
                "token_usage": type("U", (), {"input": 0, "output": 0})(),
                "tool_calls": [], "has_tool_calls": False,
            })(), "deepseek", "ds")

        packet = json.dumps({
            "context_owner": "routed",
            "should_curate_memory": True,
            "memory_curation_trigger": "signal:冲突",
            "subagent_advice": [],
        })
        # _run_sub_agent will fail (real LLM unavailable via API), but
        # curator is fail-open. The writer must still return normally.
        with patch.object(ma_mod, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = ma_mod.AWPMainAgent().execute(
                user_input="她怨我",
                session_id="p2-failopen",
                enable_agent_loop=True,
                max_iterations=1,
                round_context_packet=packet,
                record_session=False,
                context_mode="stateless_no_context",
            )
        self.assertGreater(len(result[0]), 5)
        meta = json.loads(result[2])
        c = meta.get("memory_curation", {})
        self.assertTrue(c.get("triggered") or "error" in str(c), f"curation log empty: {c}")


# ── 6. Integration tests ────────────────────────────────────────────────────

class IntegrationTests(unittest.TestCase):

    def test_full_p2_pipeline_mock(self):
        """Router → Orchestrator → MainAgent (with curator), mock LLM."""
        from comfyui_awp_rp.nodes.router_nodes import AWPRoundRouter, AWPSubAgentOrchestrator
        from comfyui_awp_rp.nodes import main_agent as ma_mod

        # 1) Router: conflict input triggers curator
        rj, _ = AWPRoundRouter().execute(
            user_input="这是一场冲突，她隐瞒真相。",
            session_id="p2-full",
            turn_index=3,
        )
        dec = json.loads(rj)
        self.assertTrue(dec["should_curate_memory"])

        # 2) Orchestrator: threads curator flag to packet
        aj, pj, _ = AWPSubAgentOrchestrator().execute(
            routing_decision_json=rj,
            user_input="这是一场冲突，她隐瞒真相。",
            session_id="p2-full",
        )
        packet = json.loads(pj)
        self.assertTrue(packet["should_curate_memory"])

        # 3) Mock curator: return valid JSON
        def fake_curator(profile_id, task, context="", max_iterations=3, **kw):
            return json.dumps([
                {"kind": "event", "summary": "冲突中她揭露了身份", "entityIds": ["语晴", "player"],
                 "importance": 0.9},
            ], ensure_ascii=False)

        call_idx = {"n": 0}
        def fake_writer(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (type("R", (), {
                "text": "她抬起眼，泪水滑落。「我姓林。」她声音轻得几乎听不见。",
                "token_usage": type("U", (), {"input": 0, "output": 0})(),
                "tool_calls": [], "has_tool_calls": False,
            })(), "deepseek", "ds")

        with patch("comfyui_awp_rp.tools.builtin.delegate_tool._run_sub_agent",
                   side_effect=fake_curator), \
             patch.object(ma_mod, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_writer
            result = ma_mod.AWPMainAgent().execute(
                user_input="这是一场冲突，她隐瞒真相。",
                session_id="p2-full",
                enable_agent_loop=True,
                max_iterations=1,
                round_context_packet=pj,
                record_session=False,
                context_mode="stateless_no_context",
            )

        self.assertGreater(len(result[0]), 10)
        meta = json.loads(result[2])
        c = meta.get("memory_curation", {})
        self.assertTrue(c.get("triggered"), f"curation not triggered: {c}")
        self.assertEqual(c.get("written", 0) + c.get("updated", 0), 1,
                         f"expected 1 ingested (written+updated): {c}")
        self.assertEqual(c.get("rejected"), 0, f"expected 0 rejected: {c}")

    def test_v1_fields_survive_p2_pipeline(self):
        """Verify V1 contract fields propagate correctly with P2 additions."""
        from comfyui_awp_rp.nodes.router_nodes import AWPRoundRouter
        rj, _ = AWPRoundRouter().execute(
            user_input="你还记得上次答应我的事吗？那天的一切。",
            session_id="p2-v1field",
            turn_index=4,
        )
        dec = json.loads(rj)
        # V1 fields must still work
        self.assertTrue(dec["should_read_memory"])
        # P2 curator may or may not trigger (periodic turn 4 + signals)
        self.assertIn("should_curate_memory", dec)


# ── 7. Closed-loop: write → persist → query → context → Writer ─────────────

class ClosedLoopE2ETests(unittest.TestCase):
    """Prove the full lifecycle: T1 curator writes → T2/T3 query returns the
    same fact → structured memory lands in MainAgent context → output doesn't
    leak internal labels."""

    def setUp(self):
        self.mgr = StructuredMemoryManager()  # uses default store (file-backed)
        self.ns = f"e2e-closed-{_uuid.uuid4().hex[:8]}"

    def test_write_then_read_in_subsequent_turn(self):
        """T1: Write "玩家答应三日之约" + "玉佩来源之谜" thread.
        T2: User asks "那件答应的事还记得吗" → fact found in packet.
        T3: Verify fact reaches MainAgent context without leaking."""
        # ── Turn 1: curator writes ──
        candidates = [
            {"kind": "event", "summary": "玩家答应三日后前往镇北旧宅",
             "entityIds": ["玩家", "语晴"], "importance": 0.9, "tags": ["承诺"]},
            {"kind": "unresolved-thread", "summary": "玉佩来源之谜",
             "entityIds": ["语晴"]},
        ]
        self.mgr.ingest_curator_candidates(self.ns, candidates, turn_index=1)

        # ── Turn 2: Orchestrator queries → fact + thread in packet ──
        from comfyui_awp_rp.nodes.router_nodes import AWPSubAgentOrchestrator
        aj, pj, _ = AWPSubAgentOrchestrator().execute(
            routing_decision_json="{}",
            user_input="那件答应的事还记得吗？",
            session_id=self.ns,
        )
        packet = json.loads(pj)
        sm = packet.get("structured_memories", {})
        facts = sm.get("story_facts", [])
        threads = sm.get("open_threads", [])
        self.assertEqual(len(facts), 1,
                         f"expected 1 story fact found, got {facts}")
        self.assertIn("三日", facts[0].get("summary", ""))
        self.assertEqual(len(threads), 1)
        self.assertIn("玉佩", threads[0].get("topic", ""))

        # ── Turn 3: MainAgent receives structured memories in context ──
        from comfyui_awp_rp.nodes import main_agent as ma_mod
        captured_system = {}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            captured_system["content"] = messages[0]["content"]
            return (type("R", (), {
                "text": "她抬起眼，唇角轻抿。「你答应过的事，我当然记得。」",
                "token_usage": type("U", (), {"input": 0, "output": 0})(),
                "tool_calls": [], "has_tool_calls": False,
            })(), "deepseek", "ds")

        with patch.object(ma_mod, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = ma_mod.AWPMainAgent().execute(
                user_input="你还记得那件答应的事吗？",
                session_id=self.ns,
                enable_agent_loop=True,
                max_iterations=1,
                round_context_packet=pj,
                record_session=False,
                context_mode="full_context",
            )

        # System prompt must contain structured memory facts
        sys_content = captured_system.get("content", "")
        self.assertIn("三日", sys_content,
                      "structured story_facts must appear in Writer context")
        self.assertIn("玉佩", sys_content,
                      "structured open_threads must appear in Writer context")

        # Output must NOT leak curator/metadata labels
        output = result[0]
        self.assertNotIn("story_fact", output.lower())
        self.assertNotIn("open_thread", output.lower())
        self.assertNotIn("structured_memories", output.lower())
        self.assertNotIn("curator", output.lower())
        self.assertNotIn("fact_key", output.lower())
        self.assertNotIn("评审认为", output)
        self.assertNotIn("导演建议", output)

    def test_fact_not_duplicated_across_turns(self):
        """Same fact written twice → only one record exists."""
        candidates_1 = [
            {"kind": "event", "summary": "语晴知道玉佩来源但未告诉玩家",
             "entityIds": ["语晴"], "importance": 0.7},
        ]
        r1 = self.mgr.ingest_curator_candidates(self.ns, candidates_1, turn_index=1)
        self.assertEqual(r1["written"], 1)
        # Write identical fact again
        r2 = self.mgr.ingest_curator_candidates(self.ns, candidates_1, turn_index=2)
        self.assertEqual(r2["written"], 0)
        self.assertEqual(r2["updated"], 1)
        # Only one record in store
        facts = self.mgr.query_story_facts(self.ns, limit=20)
        self.assertEqual(len(facts), 1)

    def test_curator_fail_does_not_block_writer(self):
        """curator LLM error must NOT prevent MainAgent from returning."""
        from comfyui_awp_rp.nodes import main_agent as ma_mod
        call_idx = {"n": 0}

        def fake_complete(node_config, messages, tools=None, tool_choice=None):
            call_idx["n"] += 1
            return (type("R", (), {
                "text": "她站着没说话。" * 5,
                "token_usage": type("U", (), {"input": 0, "output": 0})(),
                "tool_calls": [], "has_tool_calls": False,
            })(), "deepseek", "ds")

        # Packet says curate=True — curator will call _run_sub_agent which
        # tries real LLM → error via _detect_error → fail-open
        packet = json.dumps({
            "context_owner": "routed",
            "should_curate_memory": True,
            "memory_curation_trigger": "signal:冲突",
            "subagent_advice": [],
            "structured_memories": {"story_facts": [], "open_threads": [], "scene_state": None},
        })
        with patch.object(ma_mod, "create_default_router") as mk:
            mk.return_value.complete_with_tools.side_effect = fake_complete
            result = ma_mod.AWPMainAgent().execute(
                user_input="继续",
                session_id=self.ns,
                enable_agent_loop=True,
                max_iterations=1,
                round_context_packet=packet,
                record_session=False,
                context_mode="stateless_no_context",
            )
        self.assertGreater(len(result[0]), 20)
        meta = json.loads(result[2])
        c = meta.get("memory_curation", {})
        self.assertTrue(c.get("triggered") or "error" in str(c),
                        "curation must report triggered or error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
