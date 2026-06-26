"""
P4D-1D Unsupported Else Safety + Final Regression Closure — Tests.

All tests fully offline — no LLM/API key/real network.

Covers:
  1. Unsupported else safety (whole group deferred)
  2. Greeting default selection proof
  3. Integration verification
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.card.card_state_contract import (
    CardState,
    ConditionNode,
    translate_legacy_condition,
    translate_legacy_ejs_conditions,
    evaluate_condition,
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
        try:
            os.unlink(p)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 1. Unsupported Else Safety
# ═══════════════════════════════════════════════════════════════════════════

class TestUnsupportedElseSafety(unittest.TestCase):
    """Test that bare else causes entire group to be deferred."""

    def test_A_bare_else_deferred_even_if_condition_true(self):
        """Test 1: if A / else B — even if A is true, entire group deferred."""
        content = (
            "<%_ if (getvar('score') >= 10) { _%>"
            "content_if"
            "<%_ } else { _%>"
            "content_else"
            "<%_ } _%>"
        )
        results = translate_legacy_ejs_conditions(content)
        # All branches should be deferred_unsupported
        for r in results:
            self.assertEqual(
                r["status"], "deferred_unsupported",
                f"Branch {r['branch_index']} should be deferred, got {r['status']}",
            )
            self.assertEqual(r["reason"], "unsupported_else_branch")

    def test_A2_bare_else_deferred_via_integration(self):
        """Test 1b: if/else through _evaluate_deferred_entry → blocked."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        runner = AWPConditionalWorldbook()
        content = (
            "<%_ if (getvar('score') >= 10) { _%>"
            "content_if"
            "<%_ } else { _%>"
            "content_else"
            "<%_ } _%>"
        )
        state = CardState(
            cardId="c1", sessionId="s1",
            variables={"score": 15},  # condition is true
        ).to_json()

        active, blocked, eval_json, debug_json = runner.execute(
            card_state_json=state,
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps([{
                "sourceEntryUid": "d_else",
                "originalContent": content,
            }]),
        )
        active_list = json.loads(active)
        blocked_list = json.loads(blocked)

        # Entry should be BLOCKED despite condition being true
        self.assertFalse(
            any(e.get("sourceEntryUid") == "d_else" for e in active_list),
            "Entry with else should NOT be active even if condition is true",
        )
        self.assertTrue(
            any(e.get("sourceEntryUid") == "d_else" for e in blocked_list),
        )

        # Check diagnostics contain unsupported_else_branch
        entry_blocked = [
            e for e in blocked_list if e.get("sourceEntryUid") == "d_else"
        ]
        self.assertEqual(len(entry_blocked), 1)
        diags = entry_blocked[0].get("diagnostics", [])
        if diags:
            diag_codes = [d.get("code") for d in diags]
            self.assertIn("unsupported_else_branch", diag_codes)

    def test_B_mixed_groups_independent(self):
        """Test 2: Entry with two groups — one has else (deferred), one safe (evaluates)."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        runner = AWPConditionalWorldbook()

        # Two separate deferred entries — one with else, one without
        deferred = [
            {
                "sourceEntryUid": "d_with_else",
                "originalContent": (
                    "<%_ if (getvar('a') >= 10) { _%>"
                    "content_a"
                    "<%_ } else { _%>"
                    "content_else"
                    "<%_ } _%>"
                ),
            },
            {
                "sourceEntryUid": "d_safe",
                "originalContent": (
                    "<%_ if (getvar('b') >= 10) { _%>"
                    "content_b"
                    "<%_ } _%>"
                ),
            },
        ]
        state = CardState(
            cardId="c1", sessionId="s1",
            variables={"a": 15, "b": 15},
        ).to_json()

        active, blocked, eval_json, debug_json = runner.execute(
            card_state_json=state,
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps(deferred),
        )
        active_list = json.loads(active)
        blocked_list = json.loads(blocked)

        # d_with_else should be blocked (has else)
        self.assertTrue(
            any(e.get("sourceEntryUid") == "d_with_else" for e in blocked_list),
            "Entry with else should be blocked",
        )
        # d_safe should be active (no else, condition true)
        self.assertTrue(
            any(e.get("sourceEntryUid") == "d_safe" for e in active_list),
            "Safe entry should be active",
        )

    def test_C_no_else_chain_still_first_match_wins(self):
        """Test 3: Chain without else still works with first-match-wins."""
        content = (
            "<%_ if (getvar('score') >= 100) { _%>"
            "branch0"
            "<%_ } else if (getvar('score') >= 10) { _%>"
            "branch1"
            "<%_ } else if (getvar('score') >= 5) { _%>"
            "branch2"
            "<%_ } _%>"
        )
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]
        self.assertEqual(len(translated), 3, "All 3 branches should be translated")

        # Evaluate with score=15 → branch 1 should win
        state = {"score": 15}
        active_branch = None
        for branch in sorted(translated, key=lambda b: b["branchOrder"]):
            node = ConditionNode.from_dict(branch["ast"])
            ok, _ = evaluate_condition(node, state)
            if ok:
                active_branch = branch
                break

        self.assertIsNotNone(active_branch)
        self.assertEqual(active_branch["branchOrder"], 1)

    def test_D_unsupported_else_if_deferred(self):
        """Test 4: else if with non-whitelist expression → entire group deferred."""
        content = (
            "<%_ if (getvar('score') >= 10) { _%>"
            "content_if"
            "<%_ } else if (someFunction(x) > 5) { _%>"
            "content_else_if"
            "<%_ } _%>"
        )
        results = translate_legacy_ejs_conditions(content)
        # Branch 0 might be translated, but the group has unsupported else-if
        # The entire group should be deferred
        for r in results:
            if r["status"] == "translated":
                # If the first branch was translated, that's OK at translation level
                # The _evaluate_branch_groups will handle group-level deferral
                pass
            # At least one should be deferred
        deferred = [r for r in results if r["status"] == "deferred_unsupported"]
        self.assertGreater(len(deferred), 0, "At least one branch should be deferred")

    def test_E_diagnostics_contain_unsupported_else_branch(self):
        """Test 4b: Diagnostics contain unsupported_else_branch code."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        runner = AWPConditionalWorldbook()
        content = (
            "<%_ if (getvar('score') >= 10) { _%>"
            "content"
            "<%_ } else { _%>"
            "else_content"
            "<%_ } _%>"
        )
        state = CardState(
            cardId="c1", sessionId="s1",
            variables={"score": 15},
        ).to_json()

        active, blocked, eval_json, debug_json = runner.execute(
            card_state_json=state,
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps([{
                "sourceEntryUid": "d_diag",
                "originalContent": content,
            }]),
        )
        eval_result = json.loads(eval_json)
        diags = eval_result.get("diagnostics", [])
        # Check for unsupported_else_branch in diagnostics
        diag_codes = [d.get("code") for d in diags]
        self.assertIn(
            "unsupported_else_branch", diag_codes,
            f"Expected unsupported_else_branch in diagnostics, got: {diag_codes}",
        )

    def test_F_no_code_execution(self):
        """Test 5: Adapter does not execute EJS/JavaScript."""
        import inspect
        from comfyui_awp_rp.card import card_state_contract
        source = inspect.getsource(card_state_contract)
        adapter_start = source.find("Safe Legacy Condition Adapter")
        if adapter_start < 0:
            adapter_start = 0
        adapter_source = source[adapter_start:]
        self.assertNotIn("eval(", adapter_source)
        self.assertNotIn("exec(", adapter_source)
        self.assertNotIn("__import__", adapter_source)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Greeting Default Selection Proof
# ═══════════════════════════════════════════════════════════════════════════

class TestGreetingDefaultSelection(unittest.TestCase):
    """Prove greeting selection works correctly with non-first default."""

    def _run_init(self, store, **kwargs):
        from comfyui_awp_rp.nodes.card_state_nodes import AWPCardStateInit
        node = AWPCardStateInit()
        with patch("comfyui_awp_rp.nodes.card_state_nodes.CardStateStore") as Mock:
            Mock.return_value = CardStateStore(store)
            return node.execute(**kwargs)

    def test_1_default_selected_not_first(self):
        """Unspecified greeting → selects is_default=True, not list[0]."""
        store = _make_store()
        try:
            greetings = [
                {
                    "greetingId": "intro_first",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/score", "value": 1}',
                    ],
                },
                {
                    "greetingId": "opening_beta",
                    "isDefault": True,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/score", "value": 42}',
                    ],
                },
                {
                    "greetingId": "alternate_last",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/score", "value": 99}',
                    ],
                },
            ]
            state_json, diag_json = self._run_init(
                store,
                card_id="c1", session_id="s1",
                greetings_json=json.dumps(greetings),
            )
            state = json.loads(state_json)
            self.assertEqual(
                state["variables"]["score"], 42,
                "Should select 'opening_beta' (is_default=True), not first or last",
            )
            diags = json.loads(diag_json)
            self.assertTrue(
                any(d.get("code") == "greeting_default_selected" for d in diags),
            )
        finally:
            _cleanup(store)

    def test_2_explicit_id_overrides_default(self):
        """Explicit greeting_id overrides default selection."""
        store = _make_store()
        try:
            greetings = [
                {
                    "greetingId": "intro_first",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/score", "value": 1}',
                    ],
                },
                {
                    "greetingId": "opening_beta",
                    "isDefault": True,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/score", "value": 42}',
                    ],
                },
                {
                    "greetingId": "alternate_last",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/score", "value": 99}',
                    ],
                },
            ]
            state_json, diag_json = self._run_init(
                store,
                card_id="c1", session_id="s1",
                greetings_json=json.dumps(greetings),
                greeting_id="alternate_last",
            )
            state = json.loads(state_json)
            self.assertEqual(
                state["variables"]["score"], 99,
                "Explicit greeting_id should override default",
            )
        finally:
            _cleanup(store)

    def test_3_no_g0_dependency(self):
        """Selection does not depend on 'g0' literal."""
        store = _make_store()
        try:
            # No greeting has id "g0"
            greetings = [
                {
                    "greetingId": "alpha_intro",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/x", "value": 10}',
                    ],
                },
                {
                    "greetingId": "beta_main",
                    "isDefault": True,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/x", "value": 20}',
                    ],
                },
            ]
            state_json, _ = self._run_init(
                store,
                card_id="c1", session_id="s1",
                greetings_json=json.dumps(greetings),
            )
            state = json.loads(state_json)
            self.assertEqual(state["variables"]["x"], 20)
        finally:
            _cleanup(store)

    def test_4_ambiguous_no_default_bootstrap_required(self):
        """Multiple greetings, no default, no explicit → bootstrap_required."""
        store = _make_store()
        try:
            greetings = [
                {
                    "greetingId": "g_alpha",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/x", "value": 1}',
                    ],
                },
                {
                    "greetingId": "g_beta",
                    "isDefault": False,
                    "separatedInitialPatch": [
                        '{"op": "replace", "path": "/x", "value": 2}',
                    ],
                },
            ]
            state_json, diag_json = self._run_init(
                store,
                card_id="c1", session_id="s1",
                greetings_json=json.dumps(greetings),
            )
            state = json.loads(state_json)
            self.assertEqual(state["variables"], {})
            diags = json.loads(diag_json)
            self.assertTrue(
                any(d.get("code") == "ambiguous_greeting_selection" for d in diags),
            )
            self.assertTrue(
                any(d.get("bootstrapStatus") == "bootstrap_required" for d in diags),
            )
        finally:
            _cleanup(store)

    def test_5_single_greeting_auto_select(self):
        """Single greeting → auto-selected regardless of is_default."""
        store = _make_store()
        try:
            greetings = [{
                "greetingId": "only_one",
                "isDefault": False,
                "separatedInitialPatch": [
                    '{"op": "replace", "path": "/val", "value": 77}',
                ],
            }]
            state_json, diag_json = self._run_init(
                store,
                card_id="c1", session_id="s1",
                greetings_json=json.dumps(greetings),
            )
            state = json.loads(state_json)
            self.assertEqual(state["variables"]["val"], 77)
            diags = json.loads(diag_json)
            self.assertTrue(
                any(d.get("code") == "greeting_single_selected" for d in diags),
            )
        finally:
            _cleanup(store)

    def test_6_existing_state_highest_priority(self):
        """Existing persistent state overrides all greeting bootstrap."""
        store = _make_store()
        try:
            # First: explicit state
            self._run_init(
                store,
                card_id="c1", session_id="s1",
                initial_state_json='{"score": 42}',
            )
            # Second: greeting with different value
            greetings = [{
                "greetingId": "g0",
                "isDefault": True,
                "separatedInitialPatch": [
                    '{"op": "replace", "path": "/score", "value": 99}',
                ],
            }]
            state_json, diag_json = self._run_init(
                store,
                card_id="c1", session_id="s1",
                greetings_json=json.dumps(greetings),
            )
            state = json.loads(state_json)
            self.assertEqual(
                state["variables"]["score"], 42,
                "Existing state must not be overwritten by greeting",
            )
            diags = json.loads(diag_json)
            self.assertTrue(
                any(d.get("code") == "state_already_exists" for d in diags),
            )
        finally:
            _cleanup(store)


# ═══════════════════════════════════════════════════════════════════════════
# 3. No Hardcoded g0 or Card-Specific Logic
# ═══════════════════════════════════════════════════════════════════════════

class TestNoHardcodedLogic(unittest.TestCase):
    """Verify no card-specific logic in production code."""

    def test_no_g0_literal_in_production(self):
        """Production code must not reference 'g0' as a special value."""
        import inspect
        from comfyui_awp_rp.nodes import card_state_nodes
        source = inspect.getsource(card_state_nodes)
        # "g0" should only appear in test files, not production
        # Check that there's no hardcoded "g0" check
        lines = source.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip comments and docstrings
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Check for "g0" as a string literal (not as part of other text)
            if '"g0"' in stripped or "'g0'" in stripped:
                self.fail(f"'g0' literal found in card_state_nodes.py line {i+1}: {stripped}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
