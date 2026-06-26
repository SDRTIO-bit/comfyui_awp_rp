"""
P4D-2B Structured StateUpdateProposal V1 — Tests.

All tests fully offline — no LLM, no API key, no real network.
Uses fake router (mock create_default_router), pure node calls, and source checks.

Covers:
  1     QualityGate reject → router call count 0
  2     Fake router valid JSON → legal Candidate Patch
  3     cardId/sessionId/revision from CardState, not model output
  4     Same input + same ops → same patchId
  5     Different ops → different patchId
  6     Markdown fences / invalid JSON → no commitable patch
  7     Model tries to modify protected root → reject
  8     Model tries replace on non-existent path → reject
  9     Model tries add without rules → reject
  10    Rules explicitly allow add → passes
  11    Missing evidence → reject
  12    Empty ops → no_state_change, no commitable patch
  13    StateUpdateProposal never calls CardStateStore.commit_patch
  14    Workflow: Candidate Patch from StateUpdateProposal output
  15    Candidate Patch still goes through SideEffectDecision
  16    P4D-2A tests still pass (regression)
  17    P4D-1C bootstrap + ConditionalWorldbook regression pass
  18    Production source: no 桃花村 literals
"""

import inspect
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch as mock_patch

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.card.card_state_contract import CardState, CANDIDATE_PATCH_SCHEMA


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

class _Usage:
    """Minimal LlmTokenUsage stand-in for fake router."""
    def __init__(self, input=100, output=50):
        self.input = input
        self.output = output


def _make_fake_router(fake_text: str) -> MagicMock:
    """Return a MagicMock router whose complete_with_config yields fake_text."""
    router = MagicMock()
    router.complete_with_config.return_value = (fake_text, _Usage(), "test-provider", "test-model")
    return router


def _valid_model_output(operations=None, event_marks=None, evidence=None):
    """Build a valid model output JSON string."""
    ops = operations or []
    marks = event_marks or []
    evi = evidence if evidence is not None else [
        {"operationIndex": i, "quote": f"evidence for op {i}"}
        for i in range(len(ops))
    ]
    return json.dumps({
        "operations": ops,
        "eventMarks": marks,
        "evidence": evi,
    }, ensure_ascii=False)


def _default_state():
    return CardState(
        cardId="c1", sessionId="s1", revision=0,
        variables={"score": 5, "mood": "neutral"},
        eventFlags={},
        activeStageIds=[],
        sceneState={
            "location": "客栈", "time": "清晨",
            "activeCharacterIds": [], "lastAcceptedTurn": "",
        },
    )


def _default_contract():
    return json.dumps({
        "schemaId": "awp.rp.writer-contract.v1",
        "sessionId": "s1", "cardId": "c1",
        "scene": {"location": "客栈", "time": "清晨"},
        "state": {
            "variables": {}, "activeStageIds": [],
            "eligibleEventIds": [], "forbiddenStageMoves": [],
        },
    }, ensure_ascii=False)


def _quality_accepted():
    return json.dumps({"accepted": True, "decision": "accept"}, ensure_ascii=False)


def _quality_rejected():
    return json.dumps({"accepted": False, "decision": "revise"}, ensure_ascii=False)


def _run_proposal(state=None, contract=None, quality=None, reply="test reply",
                   fake_output=None, rules_json="{}", source_turn=0,
                   dry_run=False, provider="test", model="test-model"):
    """Run AWPStateUpdateProposal with injected fake router and return outputs."""
    from comfyui_awp_rp.nodes.card_state_nodes import AWPStateUpdateProposal
    node = AWPStateUpdateProposal()

    state = state or _default_state()
    contract = contract or _default_contract()
    quality = quality or _quality_accepted()

    if fake_output is None:
        fake_output = _valid_model_output()

    # Build a fake config with a provider that has an api_key.
    fake_provider = MagicMock()
    fake_provider.api_key = "fake-key-for-testing"
    fake_provider.default_model = "test-model"
    fake_config = MagicMock()
    fake_config.providers = {provider: fake_provider}

    # Mock PresetManager to return no preset (avoids disk dependency).
    fake_preset_mgr = MagicMock()
    fake_preset_mgr.resolve_preset.return_value = None

    router = _make_fake_router(fake_output)
    with mock_patch("comfyui_awp_rp.nodes.card_state_nodes.create_default_router",
                    return_value=router), \
         mock_patch("comfyui_awp_rp.nodes.card_state_nodes.get_config",
                    return_value=fake_config), \
         mock_patch("comfyui_awp_rp.nodes.card_state_nodes.PresetManager",
                    return_value=fake_preset_mgr):
        patch_json, result_json, diag_json, summary_json = node.execute(
            accepted_reply=reply,
            card_state_json=state.to_json(),
            writer_contract_json=contract if isinstance(contract, str) else json.dumps(contract, ensure_ascii=False),
            quality_decision_json=quality if isinstance(quality, str) else json.dumps(quality, ensure_ascii=False),
            provider=provider,
            model=model,
            state_update_rules_json=rules_json,
            source_turn=source_turn,
            dry_run=dry_run,
        )

    return patch_json, result_json, diag_json, summary_json, router


# ═══════════════════════════════════════════════════════════════════════════
# 1-13: Node behavior tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGateReject(unittest.TestCase):

    def test_1_gate_reject_skips_router_call(self):
        """1: QualityGate reject → no LLM call (call_count == 0)."""
        _, result_json, _, _, router = _run_proposal(
            quality=_quality_rejected(),
            fake_output='{"operations":[],"eventMarks":[],"evidence":[]}',
        )
        result = json.loads(result_json)
        self.assertEqual(result["status"], "skipped_by_gate")
        self.assertFalse(result["llmCalled"])
        router.complete_with_config.assert_not_called()


class TestPatchGeneration(unittest.TestCase):

    def test_2_valid_json_produces_legal_candidate_patch(self):
        """2: Fake router returns valid JSON → legal Candidate Patch."""
        ops = [{"op": "replace", "path": "variables.score", "value": 42}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "分数涨到了42"},
        ])
        patch_json, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "proposed")
        patch = json.loads(patch_json)
        self.assertEqual(patch["schemaId"], CANDIDATE_PATCH_SCHEMA)
        self.assertEqual(patch["cardId"], "c1")
        self.assertEqual(patch["sessionId"], "s1")
        self.assertEqual(patch["commitPolicy"], "pending")
        self.assertEqual(len(patch["operations"]), 1)
        self.assertEqual(patch["operations"][0]["path"], "variables.score")
        self.assertEqual(patch["expectedRevision"], 0)

    def test_3_identity_from_card_state_not_model(self):
        """3: cardId/sessionId/expectedRevision from CardState, not model output."""
        # Model output tries to inject identity fields — these are ignored by
        # the code which builds CandidateCardStatePatch from CardState.
        fake = json.dumps({
            "operations": [{"op": "replace", "path": "variables.score", "value": 42}],
            "eventMarks": [],
            "evidence": [{"operationIndex": 0, "quote": "分数涨到了42"}],
            "cardId": "HACKED", "sessionId": "HACKED", "patchId": "HACKED",
            "expectedRevision": 999, "commitPolicy": "auto",
        }, ensure_ascii=False)
        patch_json, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "proposed")
        patch = json.loads(patch_json)
        self.assertEqual(patch["cardId"], "c1", "cardId must come from CardState")
        self.assertEqual(patch["sessionId"], "s1", "sessionId must come from CardState")
        self.assertEqual(patch["expectedRevision"], 0, "expectedRevision must come from CardState")
        self.assertEqual(patch["commitPolicy"], "pending", "commitPolicy must be 'pending'")
        self.assertNotEqual(patch["patchId"], "HACKED", "patchId must be code-generated")

    def test_4_same_input_same_ops_same_patch_id(self):
        """4: same inputs + same operations → same patchId."""
        ops = [{"op": "replace", "path": "variables.score", "value": 42}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "分数涨到了42"},
        ])
        state = _default_state()
        p1, _, _, _, _ = _run_proposal(state=state, fake_output=fake)
        p2, _, _, _, _ = _run_proposal(state=state, fake_output=fake)
        self.assertEqual(json.loads(p1)["patchId"], json.loads(p2)["patchId"])

    def test_5_different_ops_different_patch_id(self):
        """5: different operations → different patchId."""
        state = _default_state()
        fake1 = _valid_model_output(operations=[
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        fake2 = _valid_model_output(operations=[
            {"op": "replace", "path": "variables.mood", "value": "happy"},
        ])
        p1, _, _, _, _ = _run_proposal(state=state, fake_output=fake1)
        p2, _, _, _, _ = _run_proposal(state=state, fake_output=fake2)
        self.assertNotEqual(json.loads(p1)["patchId"], json.loads(p2)["patchId"])


class TestModelOutputParsing(unittest.TestCase):

    def test_6_markdown_fences_rejected(self):
        """6a: Model returns Markdown fences → invalid_model_output, no commitable patch."""
        fenced = '```json\n{"operations":[],"eventMarks":[],"evidence":[]}\n```'
        _, result_json, _, _, _ = _run_proposal(fake_output=fenced)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_model_output")

    def test_6_invalid_json_rejected(self):
        """6b: Model returns invalid JSON → invalid_model_output."""
        _, result_json, _, _, _ = _run_proposal(fake_output="not json at all")
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_model_output")

    def test_6_explanation_text_rejected(self):
        """6c: Model returns explanation + JSON → invalid_model_output."""
        explained = "Here is the update:\n" + _valid_model_output()
        _, result_json, _, _, _ = _run_proposal(fake_output=explained)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_model_output")


class TestPatchSafety(unittest.TestCase):

    def test_7_protected_root_rejected(self):
        """7: Model tries to modify protected root → invalid_proposal."""
        ops = [{"op": "replace", "path": "revision", "value": 99}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "修改 revision"},
        ])
        _, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_proposal")

    def test_8_replace_nonexistent_path_rejected(self):
        """8: Model tries replace on non-existent path → invalid_proposal."""
        ops = [{"op": "replace", "path": "variables.never_set", "value": 1}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "设置不存在的变量"},
        ])
        _, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_proposal")

    def test_9_add_without_rules_rejected(self):
        """9: Model tries add without rules → invalid_proposal (default: add disabled)."""
        ops = [{"op": "add", "path": "variables.new_flag", "value": True}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "添加新标志"},
        ])
        _, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_proposal")

    def test_10_rules_explicitly_allow_add_passes(self):
        """10: Rules explicitly allowing add on a path → proposed (if path is new)."""
        ops = [{"op": "add", "path": "variables.new_flag", "value": True}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "添加新标志"},
        ])
        rules = json.dumps({"addPaths": ["variables.new_flag"]}, ensure_ascii=False)
        patch_json, result_json, _, _, _ = _run_proposal(
            fake_output=fake, rules_json=rules,
        )
        result = json.loads(result_json)
        self.assertEqual(result["status"], "proposed")
        patch = json.loads(patch_json)
        self.assertEqual(len(patch["operations"]), 1)
        self.assertEqual(patch["operations"][0]["op"], "add")

    def test_11_missing_evidence_rejected(self):
        """11: Operation without evidence → invalid_proposal."""
        ops = [{"op": "replace", "path": "variables.score", "value": 42}]
        fake = _valid_model_output(operations=ops, evidence=[])  # no evidence!
        _, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_proposal")

    def test_12_empty_ops_returns_no_state_change(self):
        """12: Empty operations → no_state_change, no commitable patch."""
        fake = _valid_model_output(operations=[], evidence=[])
        patch_json, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "no_state_change")
        # Candidate patch has empty operations.
        patch = json.loads(patch_json)
        self.assertEqual(patch["operations"], [])
        self.assertEqual(patch["patchId"], "")


class TestNoStoreWrite(unittest.TestCase):

    def test_13_no_store_commit_call(self):
        """13: StateUpdateProposal execute() never calls CardStateStore or its methods."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPStateUpdateProposal
        source = inspect.getsource(AWPStateUpdateProposal.execute)
        self.assertNotIn("CardStateStore", source,
                         "execute must not reference CardStateStore")
        self.assertNotIn("commit_patch", source,
                         "execute must not call commit_patch")
        # Also run a real proposal and verify no store interaction.
        ops = [{"op": "replace", "path": "variables.score", "value": 42}]
        fake = _valid_model_output(operations=ops, evidence=[
            {"operationIndex": 0, "quote": "分数涨到了42"},
        ])
        _, result_json, _, _, _ = _run_proposal(fake_output=fake)
        result = json.loads(result_json)
        self.assertEqual(result["status"], "proposed",
                         "proposal should succeed independently of store")


# ═══════════════════════════════════════════════════════════════════════════
# 14-15: Workflow wiring
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        wf_path = os.path.join(PARENT_DIR, "workflows", "rp_stateful_card_v1.json")
        with open(wf_path, "r", encoding="utf-8") as f:
            cls.wf = json.load(f)

    def _nodes_by_type(self, class_type):
        return {nid: n for nid, n in self.wf.items()
                if isinstance(n, dict) and n.get("class_type") == class_type}

    def test_14_candidate_patch_from_state_update_proposal(self):
        """14: Workflow: Candidate Patch source is StateUpdateProposal."""
        proposal_nodes = self._nodes_by_type("AWPStateUpdateProposal")
        self.assertEqual(len(proposal_nodes), 1)
        pid, pnode = next(iter(proposal_nodes.items()))

        # The proposal node receives quality_decision_json from QualityGate.
        self.assertEqual(pnode["inputs"]["quality_decision_json"], ["11", 0])
        # And card_state_json from CardStateInit.
        self.assertEqual(pnode["inputs"]["card_state_json"], ["5", 0])

        # SideEffectDecision receives candidate_card_state_patch_json from the proposal.
        se_nodes = self._nodes_by_type("AWPSideEffectDecision")
        self.assertEqual(len(se_nodes), 1)
        se_node = next(iter(se_nodes.values()))
        self.assertEqual(se_node["inputs"]["candidate_card_state_patch_json"], [pid, 0])

    def test_15_candidate_patch_still_goes_through_side_effect_decision(self):
        """15: CardStateCommit receives candidate patch AND side_effect_decision (gate)."""
        commit_nodes = self._nodes_by_type("AWPCardStateCommit")
        self.assertEqual(len(commit_nodes), 1)
        commit_node = next(iter(commit_nodes.values()))

        # candidate_card_state_patch_json comes from proposal (node 14).
        self.assertEqual(commit_node["inputs"]["candidate_card_state_patch_json"], ["14", 0])
        # side_effect_decision_json comes from SideEffectDecision (node 12).
        self.assertEqual(commit_node["inputs"]["side_effect_decision_json"], ["12", 2])


# ═══════════════════════════════════════════════════════════════════════════
# 16-18: Regression
# ═══════════════════════════════════════════════════════════════════════════

class TestRegression(unittest.TestCase):

    def test_16_p4d2a_tests_still_pass(self):
        """16: P4D-2A CardStateCommit tests still pass (regression)."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "unittest",
             "comfyui_awp_rp.test_p4d2a_card_state_commit"],
            cwd=PARENT_DIR,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            f"P4D-2A tests failed:\nstdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}",
        )

    def test_17_p4d1c_bootstrap_and_worldbook_regression(self):
        """17: P4D-1C bootstrap + ConditionalWorldbook regression pass."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "unittest",
             "comfyui_awp_rp.test_p4d1c_narrow_fixes",
             "comfyui_awp_rp.test_p4d1d_final_closure"],
            cwd=PARENT_DIR,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            f"P4D-1C/1D tests failed:\nstdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}",
        )

    def test_18_production_source_no_thc_literals(self):
        """18: Production source has no 桃花村-specific literals."""
        from comfyui_awp_rp.nodes import card_state_nodes
        source = inspect.getsource(card_state_nodes)
        forbidden = ["桃花村", "周语晴", "语晴", "桃花", "taohua", "Taohua",
                      "THC_", "PeachVillage", "peach_village"]
        found = [term for term in forbidden if term in source]
        self.assertEqual(found, [],
                         f"Found card-specific literals in production code: {found}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
