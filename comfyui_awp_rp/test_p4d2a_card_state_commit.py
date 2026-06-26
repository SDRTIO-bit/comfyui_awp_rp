"""
P4D-2A Deterministic CardState Commit V1 — Tests.

All tests fully offline — no LLM, no API key, no real network.
Uses in-memory / temp SQLite, pure node calls, and direct unit calls.

Covers:
  1-5   Commit success (gate accepted + valid patch → committed, revision bump,
        init re-read, allowed-subtree persistence, next-round worldbook sees state)
  6-11  Gate / input rejection (gate reject, side-effect disallow, missing sed,
        cardId/sessionId/schemaId mismatch, commitPolicy disallow)
  12-19 Patch safety & atomicity (protected field, illegal path, illegal op,
        type/range error, atomic multi-op, replace-on-missing rejected,
        add creates new path, greeting replace-or-add does not leak into commit)
  20-24 Revision / concurrency / replay (stale, idempotent replay,
        patch-id conflict, first-of-two wins, failure leaves store unchanged)
  25-30 Workflow (valid json, commit registered, patch→commit link,
        gate→commit link, no bypass, original workflow preserved)
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.card.card_state_contract import (
    CardState,
    CandidateCardStatePatch,
    CANDIDATE_PATCH_SCHEMA,
    COMMIT_RESULT_SCHEMA,
    apply_commit_operations_strict,
    compute_patch_hash,
)
from comfyui_awp_rp.card.card_state_store import CardStateStore
from comfyui_awp_rp.core.store import SQLiteStore


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SQLiteStore(path)
    store._test_path = path
    return store


def _cleanup(store):
    p = getattr(store, "_test_path", None)
    if p and os.path.exists(p):
        try:
            os.unlink(p)
        except OSError:
            pass


def _seed_state(store, card_id="c1", session_id="s1", variables=None, revision=0):
    """Save a CardState at a given revision into the store."""
    state = CardState(
        cardId=card_id,
        sessionId=session_id,
        revision=revision,
        variables=variables if variables is not None else {"score": 5},
        eventFlags={},
        activeStageIds=[],
        sceneState={
            "location": "起点",
            "time": "清晨",
            "activeCharacterIds": [],
            "lastAcceptedTurn": "",
        },
    )
    CardStateStore(store).save(state)
    return state


def _sed_ok(commit_policy="auto"):
    return {
        "schemaId": "awp.rp.side-effect-card-state.v1",
        "allowCardStateCommit": True,
        "reason": "accepted-pending-commit-policy",
        "commitPolicy": commit_policy,
    }


def _sed_gate_rejected():
    return {
        "schemaId": "awp.rp.side-effect-card-state.v1",
        "allowCardStateCommit": False,
        "reason": "quality-gate-rejected",
    }


def _sed_disallow():
    return {
        "schemaId": "awp.rp.side-effect-card-state.v1",
        "allowCardStateCommit": False,
        "reason": "accepted-manual-commit",
        "commitPolicy": "manual",
    }


def _make_patch(
    operations,
    card_id="c1",
    session_id="s1",
    patch_id="patch-001",
    expected_revision=0,
    commit_policy="auto",
):
    return CandidateCardStatePatch(
        cardId=card_id,
        sessionId=session_id,
        operations=operations,
        commitPolicy=commit_policy,
        patchId=patch_id,
        expectedRevision=expected_revision,
    )


def _run_commit(
    store,
    card_state,
    patch,
    sed,
    expected_revision=-1,
    allow_manual_commit=False,
):
    """Run AWPCardStateCommit with the temp store injected."""
    from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateCommit
    node = AWPCardStateCommit()
    with mock_patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as Mock:
        Mock.return_value = CardStateStore(store)
        return node.execute(
            card_state_json=card_state.to_json(),
            candidate_card_state_patch_json=patch.to_json(),
            side_effect_decision_json=json.dumps(sed, ensure_ascii=False),
            expected_revision=expected_revision,
            allow_manual_commit=allow_manual_commit,
        )


# ═══════════════════════════════════════════════════════════════════════════
# 1-5: Commit success
# ═══════════════════════════════════════════════════════════════════════════

class TestCommitSuccess(unittest.TestCase):
    """1-5: accepted gate + valid patch commits atomically."""

    def setUp(self):
        self.store = _make_store()
        self.state = _seed_state(self.store)

    def tearDown(self):
        _cleanup(self.store)

    def test_1_accepted_gate_valid_patch_commits(self):
        """1: accepted Gate + valid patch → status committed."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        updated_json, result_json, diag_json = _run_commit(
            self.store, self.state, patch, _sed_ok(),
        )
        result = json.loads(result_json)
        self.assertEqual(result["schemaId"], COMMIT_RESULT_SCHEMA)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["cardId"], "c1")
        self.assertEqual(result["sessionId"], "s1")
        self.assertEqual(result["patchId"], "patch-001")
        self.assertEqual(result["appliedOperationCount"], 1)

    def test_2_commit_bumps_revision_from_n_to_n_plus_1(self):
        """2: revision goes 0 → 1 on first commit."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        result = json.loads(result_json)
        self.assertEqual(result["previousRevision"], 0)
        self.assertEqual(result["currentRevision"], 1)

    def test_3_card_state_init_reads_committed_state_after_commit(self):
        """3: after commit, AWPCardStateInit reads the updated persisted state."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        _run_commit(self.store, self.state, patch, _sed_ok())

        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit
        node = AWPCardStateInit()
        with mock_patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as Mock:
            Mock.return_value = CardStateStore(self.store)
            state_json, diag_json = node.execute(
                card_id="c1", session_id="s1",
            )
        state = json.loads(state_json)
        self.assertEqual(state["revision"], 1, "init must read committed revision")
        self.assertEqual(state["variables"]["score"], 42, "init must read committed variables")
        diags = json.loads(diag_json)
        self.assertTrue(any(d.get("code") == "state_already_exists" for d in diags))

    def test_4_allowed_subtree_mutations_persist(self):
        """4: variables / eventFlags / sceneState / activeStageIds edits persist."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
            {"op": "add", "path": "eventFlags.met_npc", "value": True},
            {"op": "append", "path": "activeStageIds", "value": "stage_2"},
            {"op": "replace", "path": "sceneState.location", "value": "客栈"},
            {"op": "add", "path": "variables.flags.nested", "value": 1},
        ])
        updated_json, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        result = json.loads(result_json)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["appliedOperationCount"], 5)

        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.variables["score"], 42)
        self.assertEqual(persisted.eventFlags["met_npc"], True)
        self.assertEqual(persisted.activeStageIds, ["stage_2"])
        self.assertEqual(persisted.sceneState["location"], "客栈")
        self.assertEqual(persisted.variables["flags"]["nested"], 1)
        self.assertEqual(persisted.revision, 1)

    def test_5_next_round_conditional_worldbook_sees_updated_state(self):
        """5: after commit, ConditionalWorldbook reflects the new state."""
        # Before commit: score=5 → condition (score >= 42) is false → blocked.
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        wb = AWPConditionalWorldbook()
        deferred = [{
            "sourceEntryUid": "d_score",
            "originalContent": "<%_ if (getvar('score') >= 42) { _%>high<%_ } _%>",
        }]
        active_before, _, _, _ = wb.execute(
            card_state_json=self.state.to_json(),
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps(deferred),
        )
        self.assertFalse(
            any(e.get("sourceEntryUid") == "d_score" for e in json.loads(active_before)),
            "before commit the score-gated entry must be inactive",
        )

        # Commit score=42.
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        _run_commit(self.store, self.state, patch, _sed_ok())

        # Next round: reload state from store, re-evaluate.
        committed = CardStateStore(self.store).load("c1", "s1")
        active_after, _, _, _ = wb.execute(
            card_state_json=committed.to_json(),
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps(deferred),
        )
        self.assertTrue(
            any(e.get("sourceEntryUid") == "d_score" for e in json.loads(active_after)),
            "after commit the score-gated entry must be active",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6-11: Gate & input rejection
# ═══════════════════════════════════════════════════════════════════════════

class TestGateAndInputRejection(unittest.TestCase):
    """6-11: gate / input mismatches never write."""

    def setUp(self):
        self.store = _make_store()
        self.state = _seed_state(self.store)

    def tearDown(self):
        _cleanup(self.store)

    def _assert_no_write(self, result_json):
        result = json.loads(result_json)
        self.assertNotEqual(result["status"], "committed")
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.revision, 0, "revision must not change")
        self.assertEqual(persisted.variables["score"], 5, "variables must not change")

    def test_6_quality_gate_rejected_blocks_write(self):
        """6: Gate rejected → rejected_by_gate, no write."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_gate_rejected())
        result = json.loads(result_json)
        self.assertEqual(result["status"], "rejected_by_gate")
        self.assertIn("quality_gate_not_accepted", result["reasonCodes"])
        self._assert_no_write(result_json)

    def test_7_side_effect_disallow_blocks_write(self):
        """7: SideEffectDecision forbids commit → rejected_by_gate, no write."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_disallow())
        result = json.loads(result_json)
        self.assertEqual(result["status"], "rejected_by_gate")
        self.assertIn("side_effect_decision_disallows_commit", result["reasonCodes"])
        self._assert_no_write(result_json)

    def test_8_missing_side_effect_decision_blocks_write(self):
        """8: missing side_effect_decision → rejected_by_gate, no write."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateCommit
        node = AWPCardStateCommit()
        with mock_patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as Mock:
            Mock.return_value = CardStateStore(self.store)
            _, result_json, _ = node.execute(
                card_state_json=self.state.to_json(),
                candidate_card_state_patch_json=patch.to_json(),
                side_effect_decision_json="",
            )
        result = json.loads(result_json)
        self.assertEqual(result["status"], "rejected_by_gate")
        self.assertIn("side_effect_decision_missing_or_invalid", result["reasonCodes"])
        self._assert_no_write(result_json)

    def test_9_card_id_mismatch_blocks_write(self):
        """9: patch cardId != state cardId → invalid_patch, no write."""
        patch = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 42}],
            card_id="other-card",
        )
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_patch")
        self.assertTrue(any("cardId_mismatch" in r for r in result["reasonCodes"]))
        self._assert_no_write(result_json)

    def test_10_patch_schema_id_mismatch_blocks_write(self):
        """10: patch schemaId wrong → invalid_patch, no write."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},
        ])
        bad = json.loads(patch.to_json())
        bad["schemaId"] = "something.else.v2"
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateCommit
        node = AWPCardStateCommit()
        with mock_patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as Mock:
            Mock.return_value = CardStateStore(self.store)
            _, result_json, _ = node.execute(
                card_state_json=self.state.to_json(),
                candidate_card_state_patch_json=json.dumps(bad),
                side_effect_decision_json=json.dumps(_sed_ok()),
            )
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_patch")
        self.assertIn("patch_schema_id_mismatch", result["reasonCodes"])
        self._assert_no_write(result_json)

    def test_11_commit_policy_disallow_blocks_write(self):
        """11: commitPolicy='pending' → rejected_by_gate, no write."""
        patch = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 42}],
            commit_policy="pending",
        )
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok("pending"))
        result = json.loads(result_json)
        self.assertEqual(result["status"], "rejected_by_gate")
        self.assertIn("commit_policy_disallow", result["reasonCodes"])
        self._assert_no_write(result_json)


# ═══════════════════════════════════════════════════════════════════════════
# 12-19: Patch safety & atomicity
# ═══════════════════════════════════════════════════════════════════════════

class TestPatchSafetyAndAtomicity(unittest.TestCase):
    """12-19: strict patch semantics + atomicity."""

    def setUp(self):
        self.store = _make_store()
        self.state = _seed_state(self.store)

    def tearDown(self):
        _cleanup(self.store)

    def _assert_rejected_no_write(self, result_json):
        result = json.loads(result_json)
        self.assertEqual(result["status"], "invalid_patch")
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.revision, 0)
        self.assertEqual(persisted.variables["score"], 5)

    def test_12_writing_protected_field_rejected(self):
        """12: op targeting a protected field (revision) is rejected."""
        patch = _make_patch([
            {"op": "set", "path": "revision", "value": 99},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self._assert_rejected_no_write(result_json)
        reason = json.loads(result_json)["reasonCodes"]
        self.assertTrue(any("protected" in r for r in reason))

    def test_13_illegal_path_rejected(self):
        """13: unsafe path (bracket indexing) is rejected."""
        patch = _make_patch([
            {"op": "set", "path": "variables[score]", "value": 1},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self._assert_rejected_no_write(result_json)

    def test_14_illegal_operation_rejected(self):
        """14: unknown op 'destroy' is rejected."""
        patch = _make_patch([
            {"op": "destroy", "path": "variables.score", "value": 1},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self._assert_rejected_no_write(result_json)

    def test_15_type_mismatch_rejected(self):
        """15: increment on a non-numeric is rejected (type/range error)."""
        # score is numeric; append a string list, then try increment on the list.
        patch = _make_patch([
            {"op": "add", "path": "variables.tags", "value": ["a"]},
            {"op": "increment", "path": "variables.tags", "value": 1},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self._assert_rejected_no_write(result_json)
        # Also: append on a non-list must be rejected.
        patch2 = _make_patch([
            {"op": "append", "path": "variables.score", "value": 1},
        ])
        _, result_json2, _ = _run_commit(self.store, self.state, patch2, _sed_ok(),
                                         expected_revision=0)
        # Second patch has same patchId 'patch-001' as a prior attempt that did NOT
        # commit, so it is not a replay; it is re-evaluated and rejected.
        self._assert_rejected_no_write(result_json2)

    def test_16_atomic_multi_op_one_invalid_rolls_back_all(self):
        """16: one invalid op in a multi-op patch rejects the whole patch;
        the earlier valid op must NOT be persisted."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.score", "value": 42},   # valid
            {"op": "replace", "path": "variables.does_not_exist", "value": 1},  # invalid
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self._assert_rejected_no_write(result_json)
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.variables["score"], 5,
                         "valid op before the invalid one must not be applied")

    def test_17_replace_on_nonexistent_path_rejected(self):
        """17: formal candidate patch replace on a non-existent path is rejected."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.never_set", "value": 1},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self._assert_rejected_no_write(result_json)

    def test_18_add_creates_new_path(self):
        """18: add (and only add) may create a new path."""
        patch = _make_patch([
            {"op": "add", "path": "variables.new_flag", "value": True},
            {"op": "add", "path": "eventFlags.first_meeting", "value": True},
        ])
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        result = json.loads(result_json)
        self.assertEqual(result["status"], "committed")
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.variables["new_flag"], True)
        self.assertEqual(persisted.eventFlags["first_meeting"], True)

        # add on an existing path must be rejected (predictable, not replace-or-add).
        patch2 = _make_patch(
            [{"op": "add", "path": "variables.score", "value": 99}],
            patch_id="patch-002",
        )
        _, result_json2, _ = _run_commit(
            self.store,
            CardStateStore(self.store).load("c1", "s1"),
            patch2, _sed_ok(),
            expected_revision=1,
        )
        self.assertEqual(json.loads(result_json2)["status"], "invalid_patch")

    def test_19_greeting_replace_or_add_does_not_leak_into_formal_commit(self):
        """19: greeting bootstrap replace-or-add compatibility does NOT affect
        formal commit semantics. The same 'replace' on a missing path that
        greeting bootstrap would accept is rejected by the formal commit."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit

        # Greeting bootstrap: replace on a non-existent path is accepted
        # (replace-or-add compatibility) and produces a variable.
        with mock_patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as Mock:
            Mock.return_value = CardStateStore(self.store)
            init = AWPCardStateInit()
            greeting_json = json.dumps({
                "greetingId": "g1",
                "isDefault": True,
                "separatedInitialPatch": [
                    '{"op": "replace", "path": "/fresh_variable", "value": 7}',
                ],
            })
            init.execute(
                card_id="cg", session_id="sg",
                greeting_json=greeting_json,
            )
        bootstrapped = CardStateStore(self.store).load("cg", "sg")
        self.assertEqual(bootstrapped.variables.get("fresh_variable"), 7,
                         "greeting bootstrap must accept replace-or-add")

        # Formal commit on the SAME kind of missing-path replace must REJECT.
        patch = _make_patch(
            [{"op": "replace", "path": "variables.also_missing", "value": 9}],
            card_id="cg", session_id="sg", patch_id="p-g", expected_revision=0,
        )
        _, result_json, _ = _run_commit(self.store, bootstrapped, patch, _sed_ok())
        self.assertEqual(json.loads(result_json)["status"], "invalid_patch",
                         "formal commit must NOT use replace-or-add semantics")
        persisted = CardStateStore(self.store).load("cg", "sg")
        self.assertNotIn("also_missing", persisted.variables)
        self.assertEqual(persisted.revision, 0)


# ═══════════════════════════════════════════════════════════════════════════
# 20-24: Revision / concurrency / replay
# ═══════════════════════════════════════════════════════════════════════════

class TestRevisionConcurrencyReplay(unittest.TestCase):
    """20-24: revision lock, idempotency, conflict, first-wins, no-change-on-fail."""

    def setUp(self):
        self.store = _make_store()
        self.state = _seed_state(self.store)

    def tearDown(self):
        _cleanup(self.store)

    def test_20_stale_expected_revision_rejected(self):
        """20: a second patch with a stale expectedRevision is rejected."""
        # First commit: 0 → 1.
        patch_a = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 42}],
            patch_id="pa",
        )
        _run_commit(self.store, self.state, patch_a, _sed_ok())

        # Second, different patch with stale expectedRevision=0 (current is 1).
        patch_b = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 77}],
            patch_id="pb", expected_revision=0,
        )
        updated, result_json, _ = _run_commit(
            self.store,
            CardStateStore(self.store).load("c1", "s1"),
            patch_b, _sed_ok(),
            expected_revision=0,
        )
        result = json.loads(result_json)
        self.assertEqual(result["status"], "stale_revision")
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.revision, 1, "stale patch must not bump revision")
        self.assertEqual(persisted.variables["score"], 42)

    def test_21_same_patch_id_same_content_replay_is_idempotent(self):
        """21: same patchId + same content replay → idempotent_replay, no bump."""
        patch = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 42}],
            patch_id="rid-1", expected_revision=0,
        )
        _, r1, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self.assertEqual(json.loads(r1)["status"], "committed")
        self.assertEqual(json.loads(r1)["currentRevision"], 1)

        # Replay the EXACT same patch (same patchId, same content) — even though
        # its expectedRevision=0 is now stale vs current=1.
        current = CardStateStore(self.store).load("c1", "s1")
        _, r2, _ = _run_commit(self.store, current, patch, _sed_ok())
        result2 = json.loads(r2)
        self.assertEqual(result2["status"], "idempotent_replay")
        self.assertEqual(result2["currentRevision"], 1, "replay must not bump revision")
        self.assertEqual(result2["appliedOperationCount"], 0)
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.revision, 1)

    def test_22_same_patch_id_different_content_is_conflict(self):
        """22: same patchId + different content → patch_id_conflict."""
        patch_a = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 42}],
            patch_id="cid-1", expected_revision=0,
        )
        _run_commit(self.store, self.state, patch_a, _sed_ok())

        patch_b = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 999}],
            patch_id="cid-1", expected_revision=0,
        )
        current = CardStateStore(self.store).load("c1", "s1")
        _, r2, _ = _run_commit(self.store, current, patch_b, _sed_ok())
        result2 = json.loads(r2)
        self.assertEqual(result2["status"], "patch_id_conflict")
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.revision, 1)
        self.assertEqual(persisted.variables["score"], 42,
                         "conflicting patch must not change state")

    def test_23_two_different_patches_same_expected_revision_first_wins(self):
        """23: two different patches with the same expectedRevision — only the
        first commits; the second is stale."""
        patch_a = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 11}],
            patch_id="first", expected_revision=0,
        )
        _, ra, _ = _run_commit(self.store, self.state, patch_a, _sed_ok())
        self.assertEqual(json.loads(ra)["status"], "committed")

        patch_b = _make_patch(
            [{"op": "replace", "path": "variables.score", "value": 22}],
            patch_id="second", expected_revision=0,
        )
        current = CardStateStore(self.store).load("c1", "s1")
        _, rb, _ = _run_commit(self.store, current, patch_b, _sed_ok())
        self.assertEqual(json.loads(rb)["status"], "stale_revision")
        persisted = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(persisted.variables["score"], 11, "first patch wins")
        self.assertEqual(persisted.revision, 1)

    def test_24_failed_commit_leaves_store_unchanged(self):
        """24: a rejected commit leaves revision and store content unchanged."""
        patch = _make_patch([
            {"op": "replace", "path": "variables.missing", "value": 1},
        ], patch_id="fail-1")
        before = CardStateStore(self.store).load("c1", "s1")
        _, result_json, _ = _run_commit(self.store, self.state, patch, _sed_ok())
        self.assertEqual(json.loads(result_json)["status"], "invalid_patch")
        after = CardStateStore(self.store).load("c1", "s1")
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.variables, before.variables)


# ═══════════════════════════════════════════════════════════════════════════
# 25-30: Workflow
# ═══════════════════════════════════════════════════════════════════════════

class TestReferenceWorkflow(unittest.TestCase):
    """25-30: rp_stateful_card_v1.json wiring & preservation."""

    @classmethod
    def setUpClass(cls):
        cls.wf_path = os.path.join(PARENT_DIR, "workflows", "rp_stateful_card_v1.json")
        with open(cls.wf_path, "r", encoding="utf-8") as f:
            cls.wf = json.load(f)

    def _nodes_by_type(self, class_type):
        return {nid: n for nid, n in self.wf.items()
                if isinstance(n, dict) and n.get("class_type") == class_type}

    def test_25_workflow_is_valid_json_with_nodes(self):
        """25: rp_stateful_card_v1.json is valid JSON with node entries."""
        self.assertIsInstance(self.wf, dict)
        node_ids = [k for k in self.wf.keys() if k.isdigit()]
        self.assertGreaterEqual(len(node_ids), 13)

    def test_26_commit_node_registered_in_plugin_and_workflow(self):
        """26: AWPCardStateCommit is registered and present in the workflow."""
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        self.assertIn("AWPCardStateCommit", NODE_CLASS_MAPPINGS)
        commit_nodes = self._nodes_by_type("AWPCardStateCommit")
        self.assertEqual(len(commit_nodes), 1, "exactly one AWPCardStateCommit node")

    def test_27_candidate_patch_to_commit_link_exists(self):
        """27: the candidate patch source feeds AWPCardStateCommit."""
        commit_nodes = self._nodes_by_type("AWPCardStateCommit")
        commit_nid, commit_node = next(iter(commit_nodes.items()))
        patch_link = commit_node["inputs"]["candidate_card_state_patch_json"]
        self.assertEqual(len(patch_link), 2)
        src_id, _ = patch_link
        src = self.wf[src_id]
        self.assertEqual(src["class_type"], "AWPJsonInput",
                         "candidate patch source must be the external JSON input node")

    def test_28_gate_to_commit_link_exists(self):
        """28: SideEffectDecision (gate) feeds AWPCardStateCommit."""
        commit_nodes = self._nodes_by_type("AWPCardStateCommit")
        commit_nid, commit_node = next(iter(commit_nodes.items()))
        sed_link = commit_node["inputs"]["side_effect_decision_json"]
        src_id, out_idx = sed_link
        src = self.wf[src_id]
        self.assertEqual(src["class_type"], "AWPSideEffectDecision")
        # Must read the card_state_decision output (index 2).
        self.assertEqual(out_idx, 2)

    def test_29_no_candidate_patch_bypasses_gate_to_store(self):
        """29: the only store writer is AWPCardStateCommit, and it requires the
        gate (SideEffectDecision) output. No candidate patch writes to the store
        directly without going through the gate."""
        # The only store-writing node class in the workflow is AWPCardStateCommit.
        store_writers = {
            nid: n for nid, n in self.wf.items()
            if isinstance(n, dict) and n.get("class_type") == "AWPCardStateCommit"
        }
        self.assertEqual(len(store_writers), 1)
        commit_node = next(iter(store_writers.values()))
        # Its side_effect_decision input MUST come from a SideEffectDecision node.
        sed_src = commit_node["inputs"]["side_effect_decision_json"][0]
        self.assertEqual(self.wf[sed_src]["class_type"], "AWPSideEffectDecision")
        # And the SideEffectDecision must itself consume the QualityGate output.
        sed_node = self.wf[sed_src]
        qg_src = sed_node["inputs"]["quality_decision_json"][0]
        self.assertEqual(self.wf[qg_src]["class_type"], "AWPQualityGate",
                         "SideEffectDecision must be fed by QualityGate")

    def test_30_original_workflow_nodes_preserved(self):
        """30: the original nodes 1-13 are preserved with their class types and
        key wiring (not overwritten)."""
        expected_classes = {
            "1": "AWPTextInput", "2": "AWPTextInput", "3": "AWPCardImport",
            "4": "AWPCardSelect", "5": "AWPCardStateInit",
            "6": "AWPConditionalWorldbook", "7": "AWPMemoryRead",
            "8": "AWPSessionLoad", "9": "AWPRoundPreparer",
            "10": "AWPDialogueDirector", "11": "AWPQualityGate",
            "12": "AWPSideEffectDecision", "13": "AWPOutputRenderer",
        }
        for nid, cls in expected_classes.items():
            self.assertIn(nid, self.wf, f"original node {nid} must remain")
            self.assertEqual(self.wf[nid]["class_type"], cls,
                             f"node {nid} class must remain {cls}")
        # Key wiring preserved: node 5 reads card_state from init, node 11 gate
        # receives writer contract, node 12 receives quality decision from 11.
        self.assertEqual(self.wf["6"]["inputs"]["card_state_json"], ["5", 0])
        self.assertEqual(self.wf["11"]["inputs"]["reply"], ["10", 0])
        self.assertEqual(self.wf["12"]["inputs"]["quality_decision_json"], ["11", 0])


# ═══════════════════════════════════════════════════════════════════════════
# Direct unit tests for the strict applier & store (implementation evidence)
# ═══════════════════════════════════════════════════════════════════════════

class TestStrictApplierUnit(unittest.TestCase):
    """Direct unit evidence for atomicity / revision / idempotency primitives."""

    def test_strict_applier_atomic_on_error_returns_none(self):
        """Strict applier returns None + errors on any invalid op; no partial."""
        state = CardState(cardId="c1", sessionId="s1", variables={"score": 5})
        new_state, errors, applied = apply_commit_operations_strict(state, [
            {"op": "replace", "path": "variables.score", "value": 42},
            {"op": "replace", "path": "variables.missing", "value": 1},
        ])
        self.assertIsNone(new_state)
        self.assertGreater(len(errors), 0)
        self.assertEqual(applied, 0)
        # Original state untouched.
        self.assertEqual(state.variables["score"], 5)

    def test_strict_applier_replace_requires_existence(self):
        state = CardState(cardId="c1", sessionId="s1", variables={"score": 5})
        ok_state, errors, _ = apply_commit_operations_strict(state, [
            {"op": "replace", "path": "variables.score", "value": 9},
        ])
        self.assertIsNotNone(ok_state)
        self.assertEqual(ok_state.variables["score"], 9)
        self.assertEqual(errors, [])

        bad, errors2, _ = apply_commit_operations_strict(state, [
            {"op": "replace", "path": "variables.no", "value": 1},
        ])
        self.assertIsNone(bad)
        self.assertGreater(len(errors2), 0)

    def test_compute_patch_hash_stable_for_same_content(self):
        p1 = _make_patch([{"op": "replace", "path": "variables.score", "value": 1}],
                         patch_id="x")
        p2 = _make_patch([{"op": "replace", "path": "variables.score", "value": 1}],
                         patch_id="y", expected_revision=5)
        # Different patchId/expectedRevision must NOT change the content hash.
        self.assertEqual(compute_patch_hash(p1), compute_patch_hash(p2))

    def test_store_commit_patch_atomic_transaction(self):
        """store.commit_patch does idempotent-before-stale and bumps once."""
        store = _make_store()
        try:
            _seed_state(store)
            css = CardStateStore(store)
            new_state, _, applied = apply_commit_operations_strict(
                CardState(cardId="c1", sessionId="s1", variables={"score": 5}),
                [{"op": "replace", "path": "variables.score", "value": 42}],
            )
            self.assertEqual(applied, 1)
            out = css.commit_patch("c1", "s1", new_state, 0, "pid", compute_patch_hash(
                _make_patch([{"op": "replace", "path": "variables.score", "value": 42}])
            ))
            self.assertEqual(out["status"], "committed")
            self.assertEqual(out["previousRevision"], 0)
            self.assertEqual(out["currentRevision"], 1)

            # Replay → idempotent (even with stale expectedRevision=0).
            out2 = css.commit_patch("c1", "s1", new_state, 0, "pid", compute_patch_hash(
                _make_patch([{"op": "replace", "path": "variables.score", "value": 42}])
            ))
            self.assertEqual(out2["status"], "idempotent_replay")
            self.assertEqual(out2["currentRevision"], 1)
        finally:
            _cleanup(store)


if __name__ == "__main__":
    unittest.main(verbosity=2)
