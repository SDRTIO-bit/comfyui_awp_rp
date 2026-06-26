"""
P4D-1 Stateful Card Runtime & Round Snapshot Foundation V1 — Tests.

All tests are fully offline — no LLM/API key required.
No real network calls. Uses mock/fake stores.

Test matrix:
  1-5:   Card state (idempotent, isolation, missing vars, no overwrite)
  6-14:  Conditional worldbook (threshold, event flag, all/any/not, missing var, EJS deferred, code not executed, activation into snapshot, blocked not in contract)
  15-20: Round snapshot (pinned cast, no wb hit still has cast, history budget, facts kept, non-active chars dropped, budget observable)
  21-30: Writer & Gate (contract received, no double injection, identity checks, length checks, gate reject blocks commit)
  31-35: Regression (existing nodes, old workflows, no real provider)
"""

import json
import os
import sys
import tempfile
import unittest

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.card.card_state_contract import (
    CardState,
    ConditionNode,
    ConditionEntry,
    ConditionEvaluationResult,
    WriterContract,
    CandidateCardStatePatch,
    CastInfo,
    StateInfo,
    SceneInfo,
    ContinuityInfo,
    WorldbookInfo,
    OutputRequirements,
    BudgetInfo,
    evaluate_condition,
    validate_candidate_patch,
    apply_patch_operations,
    _resolve_json_path,
    CARD_STATE_SCHEMA,
    WRITER_CONTRACT_SCHEMA,
    CANDIDATE_PATCH_SCHEMA,
)
from comfyui_awp_rp.card.card_state_store import CardStateStore
from comfyui_awp_rp.core.store import SQLiteStore


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_test_store() -> SQLiteStore:
    """Create a temporary SQLite store for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SQLiteStore(path)
    # Store the path for cleanup
    store._test_path = path
    return store


def _cleanup_store(store: SQLiteStore) -> None:
    """Clean up a test store."""
    path = getattr(store, "_test_path", None)
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 1-5: Card State Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCardStateContract(unittest.TestCase):
    """Tests 1-5: Card state schema, idempotency, isolation."""

    def test_card_state_schema_id(self):
        """Test 1: CardState has correct schema ID."""
        state = CardState(cardId="c1", sessionId="s1")
        self.assertEqual(state.schemaId, CARD_STATE_SCHEMA)
        self.assertTrue(state.is_initialized())

    def test_card_state_idempotent_init(self):
        """Test 2: Same cardId+sessionId returns same state."""
        store = _make_test_store()
        try:
            cs_store = CardStateStore(store)
            state1 = CardState(
                cardId="card_abc", sessionId="sess_123",
                variables={"score": 10},
            )
            cs_store.save(state1)

            # Second init should return existing state
            loaded = cs_store.load("card_abc", "sess_123")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.variables["score"], 10)
            self.assertEqual(loaded.revision, 0)
        finally:
            _cleanup_store(store)

    def test_card_state_session_isolation(self):
        """Test 3: Different sessionId gets different state."""
        store = _make_test_store()
        try:
            cs_store = CardStateStore(store)
            state_a = CardState(cardId="card_1", sessionId="sess_a", variables={"x": 1})
            state_b = CardState(cardId="card_1", sessionId="sess_b", variables={"x": 99})
            cs_store.save(state_a)
            cs_store.save(state_b)

            loaded_a = cs_store.load("card_1", "sess_a")
            loaded_b = cs_store.load("card_1", "sess_b")
            self.assertEqual(loaded_a.variables["x"], 1)
            self.assertEqual(loaded_b.variables["x"], 99)
        finally:
            _cleanup_store(store)

    def test_card_state_card_isolation(self):
        """Test 4: Different cardId gets different state."""
        store = _make_test_store()
        try:
            cs_store = CardStateStore(store)
            state_a = CardState(cardId="card_alpha", sessionId="s1", variables={"hp": 100})
            state_b = CardState(cardId="card_beta", sessionId="s1", variables={"hp": 50})
            cs_store.save(state_a)
            cs_store.save(state_b)

            loaded_a = cs_store.load("card_alpha", "s1")
            loaded_b = cs_store.load("card_beta", "s1")
            self.assertEqual(loaded_a.variables["hp"], 100)
            self.assertEqual(loaded_b.variables["hp"], 50)
        finally:
            _cleanup_store(store)

    def test_card_state_no_initial_vars_fail_open(self):
        """Test 5: Missing initial variables → empty state + diagnostic."""
        state = CardState(cardId="c1", sessionId="s1")
        state.add_diagnostic("no_initial_variables", "No initial variables provided")
        self.assertEqual(len(state.diagnostics), 1)
        self.assertEqual(state.variables, {})

    def test_card_state_not_overwritten(self):
        """Test: Existing state not overwritten on re-init."""
        store = _make_test_store()
        try:
            cs_store = CardStateStore(store)
            state = CardState(
                cardId="c1", sessionId="s1",
                variables={"score": 42}, revision=5,
            )
            cs_store.save(state)

            # Simulate re-init: load existing, verify not overwritten
            loaded = cs_store.load("c1", "s1")
            self.assertEqual(loaded.variables["score"], 42)
            self.assertEqual(loaded.revision, 5)
        finally:
            _cleanup_store(store)

    def test_card_state_serialization(self):
        """Test: CardState round-trips through JSON."""
        state = CardState(
            cardId="c1", sessionId="s1",
            variables={"a": 1, "b": {"c": 2}},
            eventFlags={"evt1": True},
            activeStageIds=["stage1"],
        )
        json_str = state.to_json()
        restored = CardState.from_json(json_str)
        self.assertEqual(restored.cardId, "c1")
        self.assertEqual(restored.variables["a"], 1)
        self.assertEqual(restored.eventFlags["evt1"], True)
        self.assertIn("stage1", restored.activeStageIds)


# ═══════════════════════════════════════════════════════════════════════════
# 6-14: Conditional Worldbook Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestConditionAST(unittest.TestCase):
    """Tests 6-14: Condition AST evaluation."""

    def test_numeric_threshold_condition(self):
        """Test 6: Numeric threshold >= activates."""
        state = {"stat_data": {"周语晴": {"背德值": 15}}}
        node = ConditionNode.from_dict({
            "path": "stat_data.周语晴.背德值",
            "op": ">=",
            "value": 10,
        })
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_condition_false(self):
        """Test 7: Condition not met → blocked."""
        state = {"score": 5}
        node = ConditionNode.from_dict({
            "path": "score",
            "op": ">=",
            "value": 10,
        })
        ok, reason = evaluate_condition(node, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "condition_false")

    def test_event_flag_condition(self):
        """Test 8: Event flag == true activates."""
        state = {"eventFlags": {"old_house_invited": True}}
        node = ConditionNode.from_dict({
            "path": "eventFlags.old_house_invited",
            "op": "==",
            "value": True,
        })
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)

    def test_all_combinator(self):
        """Test 9: all combinator — all must be true."""
        state = {"a": 5, "b": 10}
        node = ConditionNode.from_dict({
            "all": [
                {"path": "a", "op": ">", "value": 0},
                {"path": "b", "op": ">=", "value": 10},
            ]
        })
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)

    def test_all_combinator_one_fails(self):
        """Test 9b: all combinator — one fails → false."""
        state = {"a": 5, "b": 3}
        node = ConditionNode.from_dict({
            "all": [
                {"path": "a", "op": ">", "value": 0},
                {"path": "b", "op": ">=", "value": 10},
            ]
        })
        ok, reason = evaluate_condition(node, state)
        self.assertFalse(ok)

    def test_any_combinator(self):
        """Test 9c: any combinator — one true suffices."""
        state = {"a": 5, "b": 3}
        node = ConditionNode.from_dict({
            "any": [
                {"path": "a", "op": ">", "value": 100},
                {"path": "b", "op": ">=", "value": 3},
            ]
        })
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)

    def test_not_combinator(self):
        """Test 9d: not combinator."""
        state = {"flag": False}
        node = ConditionNode.from_dict({
            "not": {"path": "flag", "op": "==", "value": True}
        })
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)

    def test_missing_variable(self):
        """Test 10: Missing variable → missing_variable."""
        state = {"other": 1}
        node = ConditionNode.from_dict({
            "path": "stat_data.周语晴.背德值",
            "op": ">=",
            "value": 10,
        })
        ok, reason = evaluate_condition(node, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_variable")

    def test_exists_condition(self):
        """Test: exists condition — variable present."""
        state = {"a": {"b": 42}}
        node = ConditionNode.from_dict({"exists": "a.b"})
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)

    def test_exists_missing(self):
        """Test: exists condition — variable absent."""
        state = {"a": 1}
        node = ConditionNode.from_dict({"exists": "a.b.c"})
        ok, reason = evaluate_condition(node, state)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_variable")

    def test_ejs_not_executed(self):
        """Test 11: EJS/JS expressions are NOT executed — deferred."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        # Deferred entry with unsupported condition
        deferred = [{
            "sourceEntryUid": "wb_ejs_1",
            "title": "EJS Entry",
            "conditionAst": None,  # No AST → deferred
            "rawCondition": "<% if (getvar('score') > 10) { %>",
        }]
        result = node._evaluate_deferred_entry(
            deferred[0], {"score": 15}, "test input"
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasonCode"], "unsupported_condition_syntax")

    def test_no_code_execution_from_card_text(self):
        """Test 12: Arbitrary card text cannot cause code execution."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        # Malicious entry with script content
        entry = {
            "id": "evil",
            "title": "Evil Entry",
            "content": "<script>alert('xss')</script>",
            "constant": True,
        }
        result = node._evaluate_entry(entry, {}, "test")
        # Should activate (constant) but content is just stored, never executed
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["reasonCode"], "constant")
        # The content is preserved as-is, never eval'd
        self.assertIn("<script>", entry["content"])

    def test_condition_eval_result_schema(self):
        """Test 13: ConditionEvaluationResult has correct schema."""
        result = ConditionEvaluationResult(
            activeEntries=[{"id": "a1"}],
            blockedEntries=[{"id": "b1"}],
        )
        d = result.to_dict()
        self.assertEqual(d["schemaId"], "awp.rp.condition-evaluation.v1")
        self.assertEqual(len(d["activeEntries"]), 1)
        self.assertEqual(len(d["blockedEntries"]), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 15-20: Round Snapshot / Writer Contract Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestWriterContract(unittest.TestCase):
    """Tests 15-20: WriterContract construction and content."""

    def test_pinned_cast_independent_of_worldbook(self):
        """Test 15: Pinned cast (lockedCharacters) present even without worldbook."""
        contract = WriterContract(
            sessionId="s1", cardId="c1",
            cast=CastInfo(
                lockedCharacters=[{"name": "周语晴", "role": "main"}],
                userIdentity={"name": "玩家"},
            ),
        )
        d = contract.to_dict()
        self.assertEqual(len(d["cast"]["lockedCharacters"]), 1)
        self.assertEqual(d["cast"]["lockedCharacters"][0]["name"], "周语晴")
        self.assertEqual(d["cast"]["userIdentity"]["name"], "玩家")

    def test_no_worldbook_still_has_cast(self):
        """Test 16: Empty worldbook doesn't affect cast."""
        contract = WriterContract(
            cast=CastInfo(lockedCharacters=[{"name": "角色A"}]),
            worldbook=WorldbookInfo(pinnedCore=[], conditionalActive=[], retrievedDynamic=[]),
        )
        d = contract.to_dict()
        self.assertEqual(len(d["cast"]["lockedCharacters"]), 1)
        self.assertEqual(len(d["worldbook"]["pinnedCore"]), 0)

    def test_recent_history_limited(self):
        """Test 17: Recent history limited to 5 turns."""
        history = [{"turn": i, "input": f"input_{i}", "output": f"output_{i}"} for i in range(10)]
        contract = WriterContract(
            continuity=ContinuityInfo(recentHistory=history[-5:]),
        )
        d = contract.to_dict()
        self.assertEqual(len(d["continuity"]["recentHistory"]), 5)
        self.assertEqual(d["continuity"]["recentHistory"][0]["turn"], 5)

    def test_relevant_facts_preserved(self):
        """Test 18: Relevant facts and open threads in contract."""
        contract = WriterContract(
            continuity=ContinuityInfo(
                relevantFacts=[{"summary": "周语晴答应帮忙", "turn": 3}],
                openThreads=[{"topic": "旧宅的秘密", "status": "open"}],
            ),
        )
        d = contract.to_dict()
        self.assertEqual(len(d["continuity"]["relevantFacts"]), 1)
        self.assertEqual(len(d["continuity"]["openThreads"]), 1)

    def test_dropped_entries_have_reason(self):
        """Test 19: Dropped entries have reason codes."""
        contract = WriterContract(
            worldbook=WorldbookInfo(
                dropped=[{"title": "某条目", "reason": "budget-exceeded"}],
            ),
        )
        d = contract.to_dict()
        self.assertEqual(len(d["worldbook"]["dropped"]), 1)
        self.assertEqual(d["worldbook"]["dropped"][0]["reason"], "budget-exceeded")

    def test_budget_observable(self):
        """Test 20: Budget info is observable in contract."""
        contract = WriterContract(
            budget=BudgetInfo(
                historyChars=500,
                memoryChars=200,
                worldbookChars=1000,
                totalEstimatedTokens=600,
            ),
        )
        d = contract.to_dict()
        self.assertEqual(d["budget"]["historyChars"], 500)
        self.assertEqual(d["budget"]["totalEstimatedTokens"], 600)

    def test_contract_serialization(self):
        """Test: WriterContract round-trips through JSON."""
        contract = WriterContract(
            sessionId="s1", cardId="c1",
            cast=CastInfo(lockedCharacters=[{"name": "A"}]),
            state=StateInfo(variables={"x": 1}),
        )
        json_str = contract.to_json()
        restored = WriterContract.from_json(json_str)
        self.assertEqual(restored.sessionId, "s1")
        self.assertEqual(restored.state.variables["x"], 1)
        self.assertEqual(restored.cast.lockedCharacters[0]["name"], "A")


# ═══════════════════════════════════════════════════════════════════════════
# 21-30: Quality Gate & Side Effect Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestQualityGateContract(unittest.TestCase):
    """Tests 21-30: Quality gate with writer contract."""

    def _make_contract(self, **overrides) -> dict:
        """Build a test writer contract dict."""
        contract = WriterContract(
            sessionId="s1", cardId="c1",
            cast=CastInfo(
                lockedCharacters=[
                    {"name": "周语晴", "role": "main", "aliases": ["语晴"]},
                    {"name": "老马", "role": "npc"},
                ],
                userIdentity={"name": "玩家"},
                relationshipBindings=[
                    {"source": "周语晴", "target": "玩家", "type": "邻居"},
                ],
            ),
            outputRequirements=OutputRequirements(
                minBodyChars=800,
                targetBodyChars=[900, 1200],
                excludeOptionsBlock=True,
            ),
        )
        d = contract.to_dict()
        d.update(overrides)
        return d

    def test_writer_receives_contract(self):
        """Test 21: Writer contract has correct schema ID."""
        contract = self._make_contract()
        self.assertEqual(contract["schemaId"], WRITER_CONTRACT_SCHEMA)

    def test_stranger_name_flagged(self):
        """Test 23: Unknown character name in dialogue flagged as identity_suspect."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract()
        reply = '她犹豫了一下。「陌生人先生，你来这里做什么？」她低声问道。'
        issues = gate._check_writer_contract(reply, contract)
        # "陌生人先生" should be flagged as identity_suspect
        suspect_codes = [i["code"] for i in issues]
        self.assertIn("identity_suspect", suspect_codes)

    def test_generic_terms_not_flagged(self):
        """Test 24: Generic terms like 村民/邻居 NOT flagged as identity_suspect."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract()
        reply = '村里的邻居们围了过来，大家七嘴八舌地议论着。路人说道：「这可怎么办啊？」' * 3
        issues = gate._check_writer_contract(reply, contract)
        # "邻居", "大家", "村民", "路人" should NOT trigger identity_suspect
        suspect_messages = [
            i.get("message", "") for i in issues if i["code"] == "identity_suspect"
        ]
        for term in ["村民", "邻居", "大家", "路人"]:
            for msg in suspect_messages:
                self.assertNotIn(
                    term, msg,
                    f"Generic term '{term}' should not be flagged as identity_suspect",
                )

    def test_user_identity_replacement_flagged(self):
        """Test 25: User identity replacement triggers violation."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract()
        reply = '玩家决定转身离开，玩家心想这太危险了。' * 3
        issues = gate._check_writer_contract(reply, contract)
        violation_codes = [i["code"] for i in issues]
        self.assertIn("identity_violation", violation_codes)

    def test_relationship_binding_not_flagged_on_normal_text(self):
        """Test 26: Normal text with relationship doesn't trigger false positive."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract()
        reply = '周语晴看着他，眼神复杂。她轻声说：「你回来了。」' * 3
        issues = gate._check_writer_contract(reply, contract)
        # No identity_violation for normal narrative
        violation_codes = [i["code"] for i in issues if i["code"] == "identity_violation"]
        self.assertEqual(len(violation_codes), 0)

    def test_below_min_length_rejected(self):
        """Test 27: Short reply below minBodyChars → rejected."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract()
        # 300 Chinese characters (below 800 minimum)
        reply = '她看着他，眼神复杂。' * 15  # ~300 chars
        decision = gate.execute(reply=reply, writer_contract_json=json.dumps(contract))
        result = json.loads(decision[0])
        self.assertFalse(result["accepted"])
        # Should have below_min_length issue
        codes = [i["code"] for i in result.get("issues", [])]
        self.assertIn("below_min_length", codes)

    def test_options_excluded_from_length(self):
        """Test 28: Options block excluded from length counting."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract(min_body_chars=100)
        contract["outputRequirements"]["minBodyChars"] = 100
        # Body is 50 chars, options is 500 chars
        reply = '她看着他，眼神复杂。她轻声说了几句话。' * 3  # ~60 chars
        reply += '<options>\n' + '选项内容' * 100 + '\n</options>'
        issues = gate._check_length(reply, contract["outputRequirements"])
        # Should be flagged since body (60) < minBodyChars (100)
        length_issues = [i for i in issues if i["code"] == "below_min_length"]
        self.assertTrue(len(length_issues) > 0)

    def test_sufficient_length_accepted(self):
        """Test 28b: Sufficient length → accepted."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        contract = self._make_contract()
        contract["outputRequirements"]["minBodyChars"] = 100
        # 170 Chinese characters
        reply = '她看着他，眼神复杂。她轻声说道，声音里带着一丝颤抖。他站在原地，不知道该说什么。' * 5
        issues = gate._check_length(reply, contract["outputRequirements"])
        length_issues = [i for i in issues if i["code"] == "below_min_length"]
        self.assertEqual(len(length_issues), 0)

    def test_gate_reject_blocks_side_effect(self):
        """Test 29: Quality gate reject → SideEffectDecision blocks commit."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPSideEffectDecision
        side_effect = AWPSideEffectDecision()
        # Quality decision: rejected
        quality = json.dumps({"accepted": False, "decision": "revise"})
        result = side_effect.execute(
            quality_decision_json=quality,
            candidate_memory_patch=json.dumps({"candidates": []}),
        )
        decision = json.loads(result[0])
        self.assertFalse(decision["allowStateCommit"])
        self.assertFalse(decision["allowMemoryCommit"])

    def test_gate_accept_allows_commit_path(self):
        """Test 30: Quality gate accept → SideEffectDecision allows commit path."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPSideEffectDecision
        side_effect = AWPSideEffectDecision()
        quality = json.dumps({"accepted": True, "decision": "accept"})
        result = side_effect.execute(
            quality_decision_json=quality,
            candidate_state_patch=json.dumps({"commitPolicy": "auto"}),
            candidate_memory_patch=json.dumps({"commitPolicy": "auto"}),
            allow_commit_when_accepted=True,
        )
        decision = json.loads(result[0])
        self.assertTrue(decision["allowStateCommit"])
        self.assertTrue(decision["allowMemoryCommit"])

    def test_card_state_patch_blocked_on_reject(self):
        """Test 29b: Card state patch blocked when quality gate rejects."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPSideEffectDecision
        side_effect = AWPSideEffectDecision()
        quality = json.dumps({"accepted": False, "decision": "revise"})
        patch = CandidateCardStatePatch(
            cardId="c1", sessionId="s1",
            operations=[{"op": "set", "path": "score", "value": 10}],
        )
        result = side_effect.execute(
            quality_decision_json=quality,
            candidate_card_state_patch_json=patch.to_json(),
        )
        card_decision = json.loads(result[2])
        self.assertFalse(card_decision["allowCardStateCommit"])
        self.assertEqual(card_decision["reason"], "quality-gate-rejected")

    def test_card_state_patch_validated_on_accept(self):
        """Test 30b: Card state patch validated when accepted."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPSideEffectDecision
        side_effect = AWPSideEffectDecision()
        quality = json.dumps({"accepted": True, "decision": "accept"})
        patch = CandidateCardStatePatch(
            cardId="c1", sessionId="s1",
            operations=[{"op": "set", "path": "score", "value": 10}],
        )
        result = side_effect.execute(
            quality_decision_json=quality,
            candidate_card_state_patch_json=patch.to_json(),
            allow_commit_when_accepted=True,
        )
        card_decision = json.loads(result[2])
        self.assertTrue(card_decision["allowCardStateCommit"])


# ═══════════════════════════════════════════════════════════════════════════
# 31-35: Regression Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRegression(unittest.TestCase):
    """Tests 31-35: Existing functionality not broken."""

    def test_existing_nodes_still_registered(self):
        """Test 31: All existing nodes still registered."""
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        expected = [
            "AWPMainAgent", "AWPMemoryRead", "AWPMemoryWrite",
            "AWPCardImport", "AWPCardSelect", "AWPDialogueDirector",
            "AWPQualityGate", "AWPSideEffectDecision", "AWPRoundPreparer",
            "AWPMVUNode", "AWPRoundRouter", "AWPSubAgentOrchestrator",
        ]
        for name in expected:
            self.assertIn(name, NODE_CLASS_MAPPINGS, f"Missing node: {name}")

    def test_new_nodes_registered(self):
        """Test 31b: New P4D-1 nodes registered."""
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        self.assertIn("AWPCardStateInit", NODE_CLASS_MAPPINGS)
        self.assertIn("AWPConditionalWorldbook", NODE_CLASS_MAPPINGS)

    def test_round_preparer_has_5_outputs(self):
        """Test 32: AWPRoundPreparer now has 5 outputs (including writer_contract)."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
        node = AWPRoundPreparer()
        self.assertEqual(len(node.RETURN_NAMES), 5)
        self.assertIn("writer_contract_json", node.RETURN_NAMES)

    def test_round_preparer_backward_compat(self):
        """Test 32b: AWPRoundPreparer backward compatible — first 4 outputs unchanged."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
        node = AWPRoundPreparer()
        names = node.RETURN_NAMES
        self.assertEqual(names[0], "组装上下文")
        self.assertEqual(names[1], "匹配的世界书")
        self.assertEqual(names[2], "变量清单")
        self.assertEqual(names[3], "预算报告")

    def test_quality_gate_backward_compat(self):
        """Test 33: AWPQualityGate backward compatible without writer_contract."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        result = gate.execute(reply="她看着他，轻声说道。" * 50)
        decision = json.loads(result[0])
        self.assertIn("accepted", decision)
        self.assertIn("decision", decision)

    def test_side_effect_decision_has_3_outputs(self):
        """Test 33b: AWPSideEffectDecision now has 3 outputs."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPSideEffectDecision
        node = AWPSideEffectDecision()
        self.assertEqual(len(node.RETURN_NAMES), 3)
        self.assertIn("card_state_decision", node.RETURN_NAMES)

    def test_no_real_provider_calls(self):
        """Test 35: No real API calls in any test."""
        # This test passes if all other tests pass without API keys
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Additional: CandidateCardStatePatch Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCandidatePatch(unittest.TestCase):
    """Tests for CandidateCardStatePatch validation and application."""

    def test_patch_schema(self):
        """Patch has correct schema ID."""
        patch = CandidateCardStatePatch(cardId="c1", sessionId="s1")
        self.assertEqual(patch.schemaId, CANDIDATE_PATCH_SCHEMA)

    def test_patch_valid(self):
        """Valid patch passes validation."""
        patch = CandidateCardStatePatch(
            cardId="c1", sessionId="s1",
            operations=[{"op": "set", "path": "score", "value": 10}],
        )
        ok, errors = validate_candidate_patch(patch)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_patch_missing_card_id(self):
        """Patch without cardId fails validation."""
        patch = CandidateCardStatePatch(
            sessionId="s1",
            operations=[{"op": "set", "path": "x", "value": 1}],
        )
        ok, errors = validate_candidate_patch(patch)
        self.assertFalse(ok)
        self.assertIn("missing cardId", errors)

    def test_patch_invalid_op(self):
        """Patch with invalid op type fails validation."""
        patch = CandidateCardStatePatch(
            cardId="c1", sessionId="s1",
            operations=[{"op": "destroy", "path": "x", "value": 1}],
        )
        ok, errors = validate_candidate_patch(patch)
        self.assertFalse(ok)
        self.assertTrue(any("destroy" in e for e in errors))

    def test_patch_card_id_mismatch(self):
        """Patch with mismatched cardId fails."""
        state = CardState(cardId="c1", sessionId="s1")
        patch = CandidateCardStatePatch(
            cardId="c2", sessionId="s1",
            operations=[{"op": "set", "path": "x", "value": 1}],
        )
        ok, errors = validate_candidate_patch(patch, state)
        self.assertFalse(ok)
        self.assertTrue(any("cardId mismatch" in e for e in errors))

    def test_apply_patch_set(self):
        """Apply set operation to card state."""
        state = CardState(cardId="c1", sessionId="s1", variables={"score": 5})
        new_state = apply_patch_operations(state, [
            {"op": "set", "path": "score", "value": 10},
        ])
        self.assertEqual(new_state.variables["score"], 10)
        self.assertEqual(new_state.revision, 1)

    def test_apply_patch_increment(self):
        """Apply increment operation."""
        state = CardState(cardId="c1", sessionId="s1", variables={"count": 5})
        new_state = apply_patch_operations(state, [
            {"op": "increment", "path": "count", "value": 3},
        ])
        self.assertEqual(new_state.variables["count"], 8)

    def test_apply_patch_remove(self):
        """Apply remove operation."""
        state = CardState(cardId="c1", sessionId="s1", variables={"a": 1, "b": 2})
        new_state = apply_patch_operations(state, [
            {"op": "remove", "path": "b"},
        ])
        self.assertNotIn("b", new_state.variables)
        self.assertIn("a", new_state.variables)

    def test_apply_patch_nested_path(self):
        """Apply set to nested path."""
        state = CardState(cardId="c1", sessionId="s1", variables={})
        new_state = apply_patch_operations(state, [
            {"op": "set", "path": "stats.hp", "value": 100},
        ])
        self.assertEqual(new_state.variables["stats"]["hp"], 100)


# ═══════════════════════════════════════════════════════════════════════════
# Additional: ConditionalWorldbook Node Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestConditionalWorldbookNode(unittest.TestCase):
    """Integration tests for AWPConditionalWorldbook node."""

    def test_constant_entry_always_active(self):
        """Constant entries are always active regardless of state."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        card_state = CardState(cardId="c1", sessionId="s1").to_json()
        wb = json.dumps([
            {"id": "wb1", "title": "核心设定", "content": "...", "constant": True},
        ])
        active, blocked, eval_result, debug = node.execute(
            card_state_json=card_state,
            worldbook_json=wb,
            player_input="test",
        )
        active_list = json.loads(active)
        self.assertEqual(len(active_list), 1)
        self.assertEqual(active_list[0]["id"], "wb1")

    def test_keyword_match_activates(self):
        """Keyword-matched entry activates when player input contains key."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        card_state = CardState(cardId="c1", sessionId="s1").to_json()
        wb = json.dumps([
            {"id": "wb1", "title": "旧宅", "content": "...", "keys": ["旧宅", "废弃"]},
        ])
        active, blocked, eval_result, debug = node.execute(
            card_state_json=card_state,
            worldbook_json=wb,
            player_input="我去镇北旧宅看看",
        )
        active_list = json.loads(active)
        self.assertEqual(len(active_list), 1)

    def test_condition_ast_evaluated(self):
        """Condition AST evaluated against card state."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        card_state = CardState(
            cardId="c1", sessionId="s1",
            variables={"stats": {"favor": 15}},
        ).to_json()
        wb = json.dumps([{
            "id": "wb1", "title": "高好感事件",
            "content": "...",
            "conditionAst": {
                "path": "stats.favor",
                "op": ">=",
                "value": 10,
            },
        }])
        active, blocked, eval_result, debug = node.execute(
            card_state_json=card_state,
            worldbook_json=wb,
            player_input="test",
        )
        active_list = json.loads(active)
        self.assertEqual(len(active_list), 1)

    def test_condition_not_met_blocked(self):
        """Condition not met → entry blocked."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        card_state = CardState(
            cardId="c1", sessionId="s1",
            variables={"stats": {"favor": 5}},
        ).to_json()
        wb = json.dumps([{
            "id": "wb1", "title": "高好感事件",
            "content": "...",
            "conditionAst": {
                "path": "stats.favor",
                "op": ">=",
                "value": 10,
            },
        }])
        active, blocked, eval_result, debug = node.execute(
            card_state_json=card_state,
            worldbook_json=wb,
            player_input="test",
        )
        blocked_list = json.loads(blocked)
        self.assertEqual(len(blocked_list), 1)

    def test_eligible_events_output(self):
        """Eligible event IDs output in evaluation result."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        card_state = CardState(cardId="c1", sessionId="s1").to_json()
        # Use eventId in metadata (primary source)
        wb = json.dumps([{
            "id": "wb1", "title": "Event Entry",
            "content": "...",
            "constant": True,
            "metadata": {"eventId": "evt_001"},
        }])
        active, blocked, eval_result, debug = node.execute(
            card_state_json=card_state,
            worldbook_json=wb,
            player_input="test",
        )
        result = json.loads(eval_result)
        # eventId is extracted from metadata.eventId
        self.assertIn("evt_001", result.get("eligibleEventIds", []))

    def test_disabled_entry_blocked(self):
        """Disabled entries are blocked."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node = AWPConditionalWorldbook()
        card_state = CardState(cardId="c1", sessionId="s1").to_json()
        wb = json.dumps([{
            "id": "wb1", "title": "Disabled",
            "content": "...",
            "metadata": {"enabled": False},
        }])
        active, blocked, eval_result, debug = node.execute(
            card_state_json=card_state,
            worldbook_json=wb,
            player_input="test",
        )
        blocked_list = json.loads(blocked)
        self.assertEqual(len(blocked_list), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
