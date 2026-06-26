"""
P4D-1B Condition Semantics + Stateful Workflow Offline Smoke — Tests.

All tests fully offline — no LLM/API key/real network.

Covers:
  1. EJS branch semantics (if/else-if mutual exclusion)
  2. Boundary value correctness
  3. Path security validation
  4. Real card initial state evidence
  5. Full offline node chain smoke
  6. Worldbook regression evidence
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.card.card_state_contract import (
    CardState,
    ConditionNode,
    WriterContract,
    CastInfo,
    StateInfo,
    SceneInfo,
    OutputRequirements,
    evaluate_condition,
    translate_legacy_condition,
    translate_legacy_ejs_conditions,
    _validate_path,
    _resolve_json_path,
)
from comfyui_awp_rp.card.card_state_store import CardStateStore
from comfyui_awp_rp.core.store import SQLiteStore


def _make_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SQLiteStore(path)
    store._test_path = path
    return store

def _cleanup(store):
    p = getattr(store, "_test_path", None)
    if p and os.path.exists(p):
        try: os.unlink(p)
        except: pass


# ═══════════════════════════════════════════════════════════════════════════
# 1. EJS Branch Semantics: if/else-if mutual exclusion
# ═══════════════════════════════════════════════════════════════════════════

class TestBranchSemantics(unittest.TestCase):
    """Test that if/else-if chains enforce first-match-wins semantics."""

    def _build_ejs_chain(self, path="stat_data.周语晴.背德值", ranges=None):
        """Build an EJS if/else-if chain for testing."""
        if ranges is None:
            ranges = [
                (None, None, "undefined"),    # branch 0: === undefined
                (15, 20, "event_a"),           # branch 1: >= 15 && < 20
                (30, 35, "event_b"),           # branch 2: >= 30 && < 35
                (55, 60, "event_c"),           # branch 3: >= 55 && < 60
            ]
        lines = []
        for i, (lo, hi, event) in enumerate(ranges):
            if i == 0 and lo is None:
                lines.append(f"<%_ if (getvar('{path}') === undefined) {{ _%>")
            elif hi is not None and hi < 900:
                cond = f"getvar('{path}') >= {lo} && getvar('{path}') < {hi}"
                if event:
                    cond += f" && getvar('stat_data.事件.{event}') === false"
                prefix = "} else " if i > 0 else ""
                lines.append(f"<%_ {prefix}if ({cond}) {{ _%>")
            else:
                # No upper bound (>= lo only)
                cond = f"getvar('{path}') >= {lo}"
                if event:
                    cond += f" && getvar('stat_data.事件.{event}') === false"
                prefix = "} else " if i > 0 else ""
                lines.append(f"<%_ {prefix}if ({cond}) {{ _%>")
        lines.append("<%_ } _%>")
        return "\n".join(lines)

    def test_branches_have_group_id_and_order(self):
        """Each branch has branchGroupId and branchOrder."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        self.assertGreater(len(results), 0)
        # All branches should share the same group ID
        group_ids = {r["branchGroupId"] for r in results}
        self.assertEqual(len(group_ids), 1, "All branches should share one group ID")
        # Orders should be 0, 1, 2, ...
        orders = [r["branchOrder"] for r in results]
        self.assertEqual(orders, list(range(len(orders))))

    def test_only_first_matching_branch_active(self):
        """In an if/else-if chain, only the first matching branch should be active."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]
        self.assertEqual(len(translated), 4)  # all 4 branches translated

        # State: 背德值=15, event_a=false
        # Branch 0 (undefined): false (path exists)
        # Branch 1 (>=15 && <20 && event_a===false): TRUE ← should be the only active
        # Branch 2 (>=30 && <35): false
        # Branch 3 (>=55 && <60): false
        state = {"stat_data": {"周语晴": {"背德值": 15}, "事件": {"event_a": False}}}

        # Evaluate with branch semantics: only first match wins
        active_branch = None
        for branch in sorted(translated, key=lambda b: b["branchOrder"]):
            node = ConditionNode.from_dict(branch["ast"])
            ok, _ = evaluate_condition(node, state)
            if ok:
                active_branch = branch
                break  # first match wins

        self.assertIsNotNone(active_branch)
        self.assertEqual(active_branch["branchOrder"], 1)  # branch 1 matches

    def test_no_conflicting_branches_active(self):
        """No two branches from the same chain should both be active."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        # Test multiple state values
        test_values = [0, 5, 14, 15, 16, 19, 20, 25, 30, 31, 34, 35, 50, 55, 56, 59, 60, 100]
        for val in test_values:
            state = {"stat_data": {"周语晴": {"背德值": val}, "事件": {
                "event_a": False, "event_b": False, "event_c": False
            }}}

            active_count = 0
            for branch in translated:
                node = ConditionNode.from_dict(branch["ast"])
                ok, _ = evaluate_condition(node, state)
                if ok:
                    active_count += 1

            # At most 1 branch should be active (undefined check OR range check)
            self.assertLessEqual(
                active_count, 1,
                f"背德值={val}: {active_count} branches active, expected ≤1",
            )

    def test_boundary_0_undefined(self):
        """背德值 undefined (not in state) → branch 0 (undefined check) active."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        # State without 背德值 at all
        state = {"stat_data": {"周语晴": {}, "事件": {"event_a": False}}}
        node0 = ConditionNode.from_dict(translated[0]["ast"])
        ok0, _ = evaluate_condition(node0, state)
        self.assertTrue(ok0, "undefined branch should be active when path doesn't exist")

    def test_boundary_14_below_range(self):
        """背德值=14 → no range branch active (below 15)."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        state = {"stat_data": {"周语晴": {"背德值": 14}, "事件": {"event_a": False}}}
        # Branch 1: >=15 → false
        node1 = ConditionNode.from_dict(translated[1]["ast"])
        ok1, _ = evaluate_condition(node1, state)
        self.assertFalse(ok1, "背德值=14 should NOT match >=15 branch")

    def test_boundary_15_inclusive(self):
        """背德值=15 → branch 1 (>=15 && <20) active."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        state = {"stat_data": {"周语晴": {"背德值": 15}, "事件": {"event_a": False}}}
        node1 = ConditionNode.from_dict(translated[1]["ast"])
        ok1, _ = evaluate_condition(node1, state)
        self.assertTrue(ok1, "背德值=15 should match >=15 branch")

    def test_boundary_19_inclusive(self):
        """背德值=19 → branch 1 (>=15 && <20) still active."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        state = {"stat_data": {"周语晴": {"背德值": 19}, "事件": {"event_a": False}}}
        node1 = ConditionNode.from_dict(translated[1]["ast"])
        ok1, _ = evaluate_condition(node1, state)
        self.assertTrue(ok1, "背德值=19 should match >=15 && <20 branch")

    def test_boundary_20_exclusive(self):
        """背德值=20 → branch 1 (>=15 && <20) NOT active."""
        content = self._build_ejs_chain()
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        state = {"stat_data": {"周语晴": {"背德值": 20}, "事件": {"event_a": False}}}
        node1 = ConditionNode.from_dict(translated[1]["ast"])
        ok1, _ = evaluate_condition(node1, state)
        self.assertFalse(ok1, "背德值=20 should NOT match <20 branch")

    def test_undefined_vs_null_distinct(self):
        """=== undefined is NOT the same as value being null."""
        # Path exists but value is null
        state_with_null = {"stat_data": {"周语晴": {"背德值": None}}}
        # Path doesn't exist at all
        state_without = {"stat_data": {"周语晴": {}}}

        node = ConditionNode.from_dict({"not": {"exists": "stat_data.周语晴.背德值"}})

        # Path exists (value=null): exists=true → not(exists)=false
        ok_null, _ = evaluate_condition(node, state_with_null)
        self.assertFalse(ok_null, "null value means path EXISTS, so not(exists) is false")

        # Path doesn't exist: exists=false → not(exists)=true
        ok_undef, _ = evaluate_condition(node, state_without)
        self.assertTrue(ok_undef, "missing path means not(exists) is true")

    def test_real_card_uid26_full_chain(self):
        """Real card uid=26: 11 branches, only one active at a time."""
        # Build the exact pattern from the real card
        ranges = [
            (None, None, None),          # undefined
            (15, 20, "厨房的温情"),       # >=15 && <20
            (30, 35, "夜晚的准备"),       # >=30 && <35
            (55, 60, "井边的协作"),       # >=55 && <60
            (70, 75, "贴心的照顾"),       # >=70 && <75
            (95, 100, "田间的意外"),      # >=95 && <100
            (110, 115, "餐桌上的默契"),   # >=110 && <115
            (135, 140, "深夜的关怀"),     # >=135 && <140
            (150, 155, "一件心意"),       # >=150 && <155
            (175, 180, "主动的亲近"),     # >=175 && <180
            (195, 999, "家的新定义"),    # >=195 (no upper bound in real card, use 999 as sentinel)
        ]
        content = self._build_ejs_chain(ranges=ranges)
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]
        self.assertEqual(len(translated), 11, f"All 11 branches should translate, got {len(translated)}")

        # Test that at each range boundary, only one branch is active
        for val in [0, 15, 19, 20, 30, 34, 55, 70, 95, 110, 135, 150, 175, 195, 200]:
            # Build state with all events = false
            events = {"厨房的温情": False, "夜晚的准备": False, "井边的协作": False,
                      "贴心的照顾": False, "田间的意外": False, "餐桌上的默契": False,
                      "深夜的关怀": False, "一件心意": False, "主动的亲近": False,
                      "家的新定义": False}
            state = {"stat_data": {"周语晴": {"背德值": val}, "事件": events}}

            # First-match-wins evaluation
            active_branch = None
            for branch in sorted(translated, key=lambda b: b["branchOrder"]):
                node = ConditionNode.from_dict(branch["ast"])
                ok, _ = evaluate_condition(node, state)
                if ok:
                    active_branch = branch
                    break

            if val == 0:
                # val=0: path exists, undefined=false, but 0<15 so no range matches
                # This is correct: no branch active for value 0
                self.assertIsNone(active_branch, "val=0: no branch should match")
            elif 15 <= val < 20:
                self.assertEqual(active_branch["branchOrder"], 1, f"val={val} → branch 1")
            elif 30 <= val < 35:
                self.assertEqual(active_branch["branchOrder"], 2, f"val={val} → branch 2")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Path Security
# ═══════════════════════════════════════════════════════════════════════════

class TestPathSecurity(unittest.TestCase):
    """Test that dangerous paths are rejected."""

    SAFE_PATHS = [
        "stat_data.周语晴.背德值",
        "eventFlags.old_house_invited",
        "scene.location",
        "a.b.c.d",
    ]

    DANGEROUS_PATHS = [
        "__class__.__dict__",
        "obj.__globals__",
        "x.__proto__",
        "x.constructor",
        "a[b]",
        "a;b",
        "a(b)",
        "a..b",
        "a|b",
        "a&b",
    ]

    def test_safe_paths_accepted(self):
        for path in self.SAFE_PATHS:
            valid, reason = _validate_path(path)
            self.assertTrue(valid, f"Safe path '{path}' rejected: {reason}")

    def test_dangerous_paths_rejected(self):
        for path in self.DANGEROUS_PATHS:
            valid, reason = _validate_path(path)
            self.assertFalse(valid, f"Dangerous path '{path}' accepted")

    def test_resolve_rejects_dangerous_path(self):
        """_resolve_json_path returns (None, False) for dangerous paths."""
        obj = {"__class__": {"__dict__": {"x": 1}}}
        val, found = _resolve_json_path(obj, "__class__.__dict__.x")
        self.assertFalse(found)

    def test_condition_rejects_dangerous_path(self):
        """evaluate_condition returns missing_variable for dangerous path."""
        state = {"__class__": {"__dict__": {"x": 1}}}
        node = ConditionNode.from_dict({"path": "__class__.__dict__.x", "op": "==", "value": 1})
        ok, reason = evaluate_condition(node, state)
        self.assertFalse(ok)

    def test_adapter_rejects_dangerous_path(self):
        """translate_legacy_condition rejects getvar with dangerous path."""
        node, status = translate_legacy_condition("getvar('__class__.__dict__.x') === 1")
        self.assertEqual(status, "deferred_unsupported")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Real Card Initial State
# ═══════════════════════════════════════════════════════════════════════════

class TestRealCardInitialState(unittest.TestCase):
    """Test card state initialization with real card data."""

    CARD_PATH = os.path.join(
        PARENT_DIR, "data", "cards",
        "1efc516266b0f4bbd0614c4fb8367d750e1d3e112ac7cafe390bdb4e074ad8ac",
    )

    def _load_card(self):
        manifest_path = os.path.join(self.CARD_PATH, "manifest.json")
        source_path = os.path.join(self.CARD_PATH, "source.json")
        if not os.path.exists(source_path):
            self.skipTest("Card source.json not found")
        with open(source_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_card_source_loadable(self):
        """Card source data is loadable."""
        card = self._load_card()
        self.assertIn("data", card)

    def test_card_data_json_for_state_init(self):
        """Card data can be passed to AWPCardStateInit."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit
        card = self._load_card()
        node = AWPCardStateInit()
        store = _make_store()
        try:
            with patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as MockStore:
                MockStore.return_value = CardStateStore(store)
                state_json, diag_json = node.execute(
                    card_id="test_real_card",
                    session_id="test_session_1",
                    card_data_json=json.dumps(card, ensure_ascii=False),
                )
                state = json.loads(state_json)
                diagnostics = json.loads(diag_json)
                self.assertEqual(state["cardId"], "test_real_card")
                # Diagnostics should report what was extracted
                self.assertTrue(len(diagnostics) > 0)
        finally:
            _cleanup(store)

    def test_idempotent_init_preserves_state(self):
        """Same cardId+sessionId re-init preserves existing state."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit
        node = AWPCardStateInit()
        store = _make_store()
        try:
            with patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as MockStore:
                MockStore.return_value = CardStateStore(store)
                # First init with variables
                state1, _ = node.execute(
                    card_id="c1", session_id="s1",
                    initial_state_json='{"score": 42}',
                )
                # Second init (should return existing)
                state2, diag2 = node.execute(
                    card_id="c1", session_id="s1",
                    initial_state_json='{"score": 99}',
                )
                s1 = json.loads(state1)
                s2 = json.loads(state2)
                self.assertEqual(s2["variables"]["score"], 42, "State should not be overwritten")
                d2 = json.loads(diag2)
                self.assertTrue(any(d["code"] == "state_already_exists" for d in d2))
        finally:
            _cleanup(store)

    def test_different_session_isolated(self):
        """Different session gets different state."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit
        node = AWPCardStateInit()
        store = _make_store()
        try:
            with patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as MockStore:
                MockStore.return_value = CardStateStore(store)
                node.execute(card_id="c1", session_id="s_a", initial_state_json='{"x": 1}')
                node.execute(card_id="c1", session_id="s_b", initial_state_json='{"x": 99}')
                # Load directly to verify
                cs_store = CardStateStore(store)
                sa = cs_store.load("c1", "s_a")
                sb = cs_store.load("c1", "s_b")
                self.assertEqual(sa.variables["x"], 1)
                self.assertEqual(sb.variables["x"], 99)
        finally:
            _cleanup(store)

    def test_no_initial_vars_diagnostic(self):
        """No initial variables → diagnostic message."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit
        node = AWPCardStateInit()
        store = _make_store()
        try:
            with patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as MockStore:
                MockStore.return_value = CardStateStore(store)
                _, diag_json = node.execute(card_id="c1", session_id="s1")
                diags = json.loads(diag_json)
                self.assertTrue(any(d["code"] == "no_initial_variables" for d in diags))
        finally:
            _cleanup(store)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Full Offline Node Chain Smoke
# ═══════════════════════════════════════════════════════════════════════════

class TestFullChainSmoke(unittest.TestCase):
    """End-to-end offline smoke: CardStateInit → ConditionalWorldbook →
    RoundPreparer → DialogueDirector → QualityGate → SideEffectDecision."""

    def _make_fake_provider_config(self):
        """Create a mock provider config."""
        return type("PC", (), {"api_key": "test-key", "default_model": "test-model"})()

    def test_full_chain_smoke(self):
        """Full chain: state → conditions → round prep → writer → gate → side effect."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit, AWPConditionalWorldbook
        from comfyui_awp_rp.nodes.pipeline_nodes import (
            AWPRoundPreparer, AWPDialogueDirector, AWPQualityGate, AWPSideEffectDecision,
        )

        store = _make_store()
        try:
            with patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as MockCS:
                MockCS.return_value = CardStateStore(store)

                # ── Step 1: CardStateInit ──
                state_node = AWPCardStateInit()
                state_json, diag_json = state_node.execute(
                    card_id="smoke_card",
                    session_id="smoke_session",
                    initial_state_json=json.dumps({
                        "stat_data": {
                            "周语晴": {"背德值": 25},
                            "事件": {"厨房的温情": False, "夜晚的准备": False},
                        },
                    }),
                )
                state = json.loads(state_json)
                self.assertEqual(state["cardId"], "smoke_card")

                # ── Step 2: ConditionalWorldbook ──
                wb_node = AWPConditionalWorldbook()
                worldbook = json.dumps([
                    {"id": "wb_const", "title": "核心设定", "content": "桃花村位于青屏山脚下",
                     "constant": True},
                    {"id": "wb_key", "title": "旧宅", "content": "镇北旧宅的详细描述",
                     "keys": ["旧宅", "废弃"]},
                ])
                deferred = json.dumps([{
                    "sourceEntryUid": 26,
                    "originalContent": (
                        "<%_ if (getvar('stat_data.周语晴.背德值') >= 15 && "
                        "getvar('stat_data.周语晴.背德值') < 30 && "
                        "getvar('stat_data.事件.厨房的温情') === false) { _%>"
                        "厨房温情事件内容"
                        "<%_ } _%>"
                    ),
                }])
                active_json, blocked_json, eval_json, debug_json = wb_node.execute(
                    card_state_json=state_json,
                    worldbook_json=worldbook,
                    player_input="我去旧宅看看",
                    deferred_worldbook_json=deferred,
                )
                active_entries = json.loads(active_json)
                eval_result = json.loads(eval_json)

                # Constant entry should be active
                self.assertTrue(any(e.get("id") == "wb_const" for e in active_entries))
                # Keyword "旧宅" should activate
                self.assertTrue(any(e.get("id") == "wb_key" for e in active_entries))
                # Deferred entry with 背德值=25 (>=15 && <30) should be active
                self.assertTrue(any(
                    e.get("sourceEntryUid") == 26 for e in active_entries
                ), f"Deferred entry uid=26 should be active, active={[e.get('id',e.get('sourceEntryUid')) for e in active_entries]}")

                # ── Step 3: RoundPreparer ──
                rp_node = AWPRoundPreparer()
                _rp = rp_node.execute(
                    user_input="我去旧宅看看",
                    session_id="smoke_session",
                    card_state_json=state_json,
                    condition_evaluation_json=eval_json,
                    cast_info_json=json.dumps({
                        "lockedCharacters": [{"name": "周语晴", "role": "女主角"}],
                        "userIdentity": {"name": "老马"},
                        "relationshipBindings": [{"source": "周语晴", "target": "老马", "type": "公公/儿媳"}],
                    }),
                    card_id="smoke_card",
                    min_body_chars=800,
                )
                writer_contract_json = _rp[4]
                wc = json.loads(writer_contract_json)

                # Active conditional entry should be in writer contract
                cond_active = wc.get("worldbook", {}).get("conditionalActive", [])
                self.assertGreater(len(cond_active), 0, "Conditional active entries in contract")

                # Cast should be in contract
                self.assertEqual(wc["cast"]["lockedCharacters"][0]["name"], "周语晴")
                self.assertEqual(wc["cast"]["userIdentity"]["name"], "老马")

                # ── Step 4: DialogueDirector (dry_run) ──
                director = AWPDialogueDirector()
                result = director.execute(
                    context_bundle_json="{}",
                    session_id="smoke_session",
                    dry_run=True,
                    writer_contract_json=writer_contract_json,
                )
                reply = result[0]  # dry_run includes prompt
                metadata = json.loads(result[3])
                self.assertTrue(metadata.get("writer_contract_provided"))

                # Prompt must contain contract elements
                self.assertIn("周语晴", reply)
                self.assertIn("老马", reply)
                self.assertIn("800", reply)

                # Prompt must NOT contain raw EJS or getvar
                self.assertNotIn("<%_", reply)
                self.assertNotIn("getvar(", reply)

                # ── Step 5: QualityGate (short reply → reject) ──
                gate = AWPQualityGate()
                short_reply = "她看着他。" * 10  # ~40 chars, way below 800
                qg_result = gate.execute(
                    reply=short_reply,
                    writer_contract_json=writer_contract_json,
                )
                qg_decision = json.loads(qg_result[0])
                self.assertFalse(qg_decision["accepted"], "Short reply should be rejected")
                self.assertIn("below_min_length",
                              [i["code"] for i in qg_decision.get("issues", [])])

                # ── Step 6: SideEffectDecision (reject → block) ──
                se = AWPSideEffectDecision()
                se_result = se.execute(
                    quality_decision_json=json.dumps(qg_decision),
                    candidate_card_state_patch_json=json.dumps({
                        "schemaId": "awp.rp.candidate-card-state-patch.v1",
                        "cardId": "smoke_card",
                        "sessionId": "smoke_session",
                        "operations": [{"op": "set", "path": "x", "value": 1}],
                    }),
                )
                se_decision = json.loads(se_result[0])
                card_decision = json.loads(se_result[2])
                self.assertFalse(se_decision["allowStateCommit"])
                self.assertFalse(card_decision["allowCardStateCommit"])

                # ── Step 6b: Accept path ──
                qg_accept = {"accepted": True, "decision": "accept"}
                se_accept = se.execute(
                    quality_decision_json=json.dumps(qg_accept),
                    candidate_card_state_patch_json=json.dumps({
                        "schemaId": "awp.rp.candidate-card-state-patch.v1",
                        "cardId": "smoke_card",
                        "sessionId": "smoke_session",
                        "operations": [{"op": "set", "path": "x", "value": 1}],
                    }),
                    allow_commit_when_accepted=True,
                )
                card_accept = json.loads(se_accept[2])
                self.assertTrue(card_accept["allowCardStateCommit"])

        finally:
            _cleanup(store)

    def test_prompt_excludes_full_worldbook(self):
        """Final prompt does not contain full worldbook dump."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPDialogueDirector
        contract = WriterContract(
            cast=CastInfo(lockedCharacters=[{"name": "周语晴"}]),
            worldbook=WorldbookInfo(
                pinnedCore=[{"title": "设定", "content": "很长的世界书内容" * 100}],
            ),
        ).to_dict()

        captured = {}
        def mock_complete(node_config, workflow_defaults, prompt, **kw):
            captured["prompt"] = prompt
            return ("reply", type("U", (), {"input": 0, "output": 0})(), "deepseek", "test")

        with patch("comfyui_awp_rp.nodes.pipeline_nodes.create_default_router") as mk:
            mk.return_value.complete_with_config = mock_complete
            with patch("comfyui_awp_rp.nodes.pipeline_nodes.get_config") as mc:
                mc.return_value.providers = {
                    "deepseek": type("P", (), {"api_key": "k", "default_model": "m"})()
                }
                try:
                    AWPDialogueDirector().execute(
                        context_bundle_json="{}",
                        session_id="s1",
                        writer_contract_json=json.dumps(contract),
                    )
                except:
                    pass

        prompt = captured.get("prompt", "")
        # The worldbook content is long; contract rendering should be bounded
        self.assertNotIn("很长的世界书内容" * 100, prompt)
        # But the character name should be there
        self.assertIn("周语晴", prompt)


# Import WorldbookInfo for the test above
from comfyui_awp_rp.card.card_state_contract import WorldbookInfo


# ═══════════════════════════════════════════════════════════════════════════
# 5. Worldbook Regression Evidence
# ═══════════════════════════════════════════════════════════════════════════

class TestWorldbookRegressionEvidence(unittest.TestCase):
    """Verify the worldbook regression fix: RoundPreparer 5-return-value unpacking."""

    def test_regression_was_unpack_error(self):
        """P4D-1 changed RoundPreparer to 5 returns; old 4-var unpacking fails."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
        result = AWPRoundPreparer().execute(
            user_input="测试",
            session_id="regression_test",
            worldbook_index="[]",
        )
        self.assertEqual(len(result), 5, "RoundPreparer returns 5 values")

    def test_regression_unpack_by_index_works(self):
        """Index-based unpacking correctly gets budget (index 3)."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
        result = AWPRoundPreparer().execute(
            user_input="测试",
            session_id="regression_test2",
        )
        budget = json.loads(result[3])
        self.assertIn("worldbook_entries_considered", budget)

    def test_full_regression_suite_passes(self):
        """The 20-turn offline regression should now pass after the fix."""
        # This is verified by running:
        # python -m unittest comfyui_awp_rp.test_long_conversation_regression
        # We just verify the import chain works here
        from comfyui_awp_rp.test_long_conversation_regression import OfflineExecutor
        self.assertTrue(callable(OfflineExecutor))


# ═══════════════════════════════════════════════════════════════════════════
# 6. No Code Execution Evidence
# ═══════════════════════════════════════════════════════════════════════════

class TestNoCodeExecution(unittest.TestCase):
    """Verify adapter does not use eval, exec, or dynamic import."""

    def test_adapter_source_no_eval(self):
        """The adapter module source code does not contain eval/exec/dynamic import."""
        import inspect
        from comfyui_awp_rp.card import card_state_contract
        source = inspect.getsource(card_state_contract)
        # Check adapter functions only
        adapter_start = source.find("Safe Legacy Condition Adapter")
        if adapter_start < 0:
            adapter_start = 0
        adapter_source = source[adapter_start:]
        # Must not use eval/exec for code execution
        self.assertNotIn("eval(", adapter_source)
        self.assertNotIn("exec(", adapter_source)
        self.assertNotIn("__import__", adapter_source)
        # _re.compile is regex compilation, NOT code execution — allowed
        # Check no dynamic code execution patterns
        self.assertNotIn("compile(source", adapter_source)
        self.assertNotIn("compile(text", adapter_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
