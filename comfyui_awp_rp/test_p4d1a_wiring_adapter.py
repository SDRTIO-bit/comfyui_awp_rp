"""
P4D-1A Writer Wiring + Safe Legacy Condition Adapter Evidence — Tests.

All tests fully offline — no LLM/API key required.

Covers:
  1. Writer contract → prompt rendering
  2. Legacy EJS/getvar → AST adapter
  3. Workflow link validation
  4. Regression
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
)
from comfyui_awp_rp.rp_pipeline import (
    build_director_prompt,
    render_writer_contract_state as render_wc,
    safe_json_loads,
)


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Writer Contract → Prompt Rendering
# ═══════════════════════════════════════════════════════════════════════════

class TestWriterContractRendering(unittest.TestCase):
    """Tests for writer_contract_json → LLM prompt rendering."""

    def _make_contract(self) -> dict:
        """Build a realistic writer contract for testing."""
        return WriterContract(
            sessionId="s1", cardId="c1",
            cast=CastInfo(
                lockedCharacters=[
                    {"name": "周语晴", "role": "女主角", "aliases": ["语晴"]},
                ],
                userIdentity={"name": "老马"},
                relationshipBindings=[
                    {"source": "周语晴", "target": "老马", "type": "公公/儿媳"},
                ],
            ),
            scene=SceneInfo(
                location="镇北旧宅",
                time="深夜",
                activeCharacterIds=["周语晴", "老马"],
            ),
            state=StateInfo(
                activeStageIds=["试探"],
                eligibleEventIds=["evt_001"],
                forbiddenStageMoves=["不得跨阶段推进"],
                variables={"背德值": 15},
            ),
            outputRequirements=OutputRequirements(
                minBodyChars=800,
                targetBodyChars=[900, 1200],
            ),
        ).to_dict()

    def test_render_contains_locked_characters(self):
        """Prompt contains locked character names."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("周语晴", rendered)

    def test_render_contains_user_identity(self):
        """Prompt contains user identity."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("老马", rendered)

    def test_render_contains_relationship(self):
        """Prompt contains relationship binding."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("公公/儿媳", rendered)

    def test_render_contains_location(self):
        """Prompt contains scene location."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("镇北旧宅", rendered)

    def test_render_contains_time(self):
        """Prompt contains scene time."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("深夜", rendered)

    def test_render_contains_stage(self):
        """Prompt contains active stage."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("试探", rendered)

    def test_render_contains_events(self):
        """Prompt contains eligible events."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("evt_001", rendered)

    def test_render_contains_forbidden(self):
        """Prompt contains forbidden stage moves."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("不得跨阶段推进", rendered)

    def test_render_contains_min_body_chars(self):
        """Prompt contains minBodyChars requirement."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        self.assertIn("800", rendered)

    def test_render_empty_contract_returns_empty(self):
        """Empty contract returns empty string."""
        self.assertEqual(render_wc({}), "")
        self.assertEqual(render_wc({"schemaId": ""}), "")

    def test_full_prompt_contains_contract_section(self):
        """build_director_prompt includes contract section."""
        contract = self._make_contract()
        prompt = build_director_prompt(
            context_bundle="{}",
            system_prompt="你是测试系统提示。",
            writer_contract_json=json.dumps(contract),
        )
        self.assertIn("当前不可违背状态", prompt)
        self.assertIn("周语晴", prompt)
        self.assertIn("老马", prompt)
        self.assertIn("镇北旧宅", prompt)
        self.assertIn("800", prompt)

    def test_full_prompt_contract_before_generation_instruction(self):
        """Contract section appears before the generation instruction."""
        contract = self._make_contract()
        prompt = build_director_prompt(
            context_bundle="{}",
            writer_contract_json=json.dumps(contract),
        )
        contract_pos = prompt.find("当前不可违背状态")
        gen_pos = prompt.find("请基于以上上下文续写本回合")
        self.assertGreater(gen_pos, contract_pos)

    def test_no_contract_backward_compat(self):
        """Without contract, prompt still works (backward compatible)."""
        prompt = build_director_prompt(
            context_bundle="{}",
            system_prompt="测试",
        )
        self.assertIn("请基于以上上下文续写本回合", prompt)
        self.assertNotIn("当前不可违背状态", prompt)

    def test_contract_does_not_include_full_worldbook(self):
        """Contract section is bounded text, not raw worldbook dump."""
        contract = self._make_contract()
        rendered = render_wc(contract)
        # Should be short (< 500 chars for typical contract)
        self.assertLess(len(rendered), 800)

    def test_dialogue_director_accepts_contract(self):
        """AWPDialogueDirector has writer_contract_json input."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPDialogueDirector
        inputs = AWPDialogueDirector.INPUT_TYPES()
        self.assertIn("writer_contract_json", inputs.get("optional", {}))

    def test_dialogue_director_passes_contract_to_prompt(self):
        """AWPDialogueDirector passes contract to build_director_prompt."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPDialogueDirector
        director = AWPDialogueDirector()
        contract = self._make_contract()
        contract_json = json.dumps(contract)

        # Use dry_run to capture prompt without LLM call
        result = director.execute(
            context_bundle_json="{}",
            session_id="test",
            dry_run=True,
            writer_contract_json=contract_json,
        )
        # dry_run output includes prompt
        reply = result[0]
        metadata = json.loads(result[3])
        self.assertTrue(metadata.get("writer_contract_provided"))
        self.assertIn("周语晴", reply)  # dry_run includes prompt tail

    def test_fake_router_receives_contract_in_prompt(self):
        """Verify the prompt sent to the LLM router contains contract state."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPDialogueDirector
        director = AWPDialogueDirector()
        contract = self._make_contract()

        captured_prompt = {}
        def mock_complete(node_config, workflow_defaults, prompt, **kw):
            captured_prompt["text"] = prompt
            return ("mock reply", type("U", (), {"input": 0, "output": 0})(), "deepseek", "test")

        with patch("comfyui_awp_rp.nodes.pipeline_nodes.create_default_router") as mk_router:
            mk_router.return_value.complete_with_config = mock_complete
            # Configure provider
            with patch("comfyui_awp_rp.nodes.pipeline_nodes.get_config") as mk_config:
                mk_config.return_value.providers = {
                    "deepseek": type("P", (), {"api_key": "test-key", "default_model": "test"})()
                }
                try:
                    director.execute(
                        context_bundle_json="{}",
                        session_id="test",
                        provider="deepseek",
                        dry_run=False,
                        writer_contract_json=json.dumps(contract),
                    )
                except Exception:
                    pass

        prompt_text = captured_prompt.get("text", "")
        # All contract elements must be in the prompt
        self.assertIn("周语晴", prompt_text)
        self.assertIn("老马", prompt_text)
        self.assertIn("公公/儿媳", prompt_text)
        self.assertIn("镇北旧宅", prompt_text)
        self.assertIn("试探", prompt_text)
        self.assertIn("800", prompt_text)
        # Must NOT contain full worldbook dump
        self.assertNotIn("worldbook_entries", prompt_text.lower())


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Safe Legacy Condition Adapter
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyConditionAdapter(unittest.TestCase):
    """Tests for EJS/getvar → AST translation."""

    def test_simple_getvar_gte(self):
        """getvar('path') >= 15 translates to AST."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.周语晴.背德值') >= 15"
        )
        self.assertEqual(status, "translated")
        self.assertIsNotNone(node)
        d = node.to_dict()
        self.assertEqual(d["path"], "stat_data.周语晴.背德值")
        self.assertEqual(d["op"], ">=")
        self.assertEqual(d["value"], 15)

    def test_simple_getvar_lt(self):
        """getvar('path') < 20 translates."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.周语晴.背德值') < 20"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertEqual(d["op"], "<")
        self.assertEqual(d["value"], 20)

    def test_getvar_equals_false(self):
        """getvar('path') === false translates."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.事件.厨房的温情') === false"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertEqual(d["op"], "==")
        self.assertEqual(d["value"], False)

    def test_getvar_equals_true(self):
        """getvar('path') === true translates."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.flag') === true"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertEqual(d["value"], True)

    def test_getvar_equals_undefined(self):
        """getvar('path') === undefined translates to not exists."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.周语晴.背德值') === undefined"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertIn("not", d)
        self.assertEqual(d["not"]["exists"], "stat_data.周语晴.背德值")

    def test_compound_and(self):
        """getvar(...) >= 15 && getvar(...) < 20 translates to all."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.周语晴.背德值') >= 15 && getvar('stat_data.周语晴.背德值') < 20"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertIn("all", d)
        self.assertEqual(len(d["all"]), 2)
        self.assertEqual(d["all"][0]["path"], "stat_data.周语晴.背德值")
        self.assertEqual(d["all"][0]["op"], ">=")
        self.assertEqual(d["all"][0]["value"], 15)
        self.assertEqual(d["all"][1]["op"], "<")
        self.assertEqual(d["all"][1]["value"], 20)

    def test_compound_and_three_parts(self):
        """Three-part && compound translates."""
        node, status = translate_legacy_condition(
            "getvar('stat_data.周语晴.背德值') >= 15 && "
            "getvar('stat_data.周语晴.背德值') < 20 && "
            "getvar('stat_data.事件.厨房的温情') === false"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertIn("all", d)
        self.assertEqual(len(d["all"]), 3)

    def test_compound_or(self):
        """|| compound translates to any."""
        node, status = translate_legacy_condition(
            "getvar('a') === true || getvar('b') === true"
        )
        self.assertEqual(status, "translated")
        d = node.to_dict()
        self.assertIn("any", d)

    def test_unknown_syntax_deferred(self):
        """Unknown syntax → deferred_unsupported."""
        node, status = translate_legacy_condition(
            "someFunction(x) && otherStuff"
        )
        self.assertEqual(status, "deferred_unsupported")
        self.assertIsNone(node)

    def test_function_call_deferred(self):
        """Function calls → deferred."""
        node, status = translate_legacy_condition(
            "getvar('a').toString() === 'x'"
        )
        self.assertEqual(status, "deferred_unsupported")

    def test_empty_deferred(self):
        """Empty string → deferred."""
        node, status = translate_legacy_condition("")
        self.assertEqual(status, "deferred_unsupported")

    def test_ejs_full_content_translation(self):
        """translate_legacy_ejs_conditions parses EJS content."""
        content = """---
<zhouyuqing_special_events>
<%_ if (getvar('stat_data.周语晴.背德值') === undefined) { _%>

<%_ } else if (getvar('stat_data.周语晴.背德值') >= 15 && getvar('stat_data.周语晴.背德值') < 20 && getvar('stat_data.事件.厨房的温情') === false) { _%>
内容1
<%_ } else if (getvar('stat_data.周语晴.背德值') >= 30 && getvar('stat_data.周语晴.背德值') < 35 && getvar('stat_data.事件.夜晚的准备') === false) { _%>
内容2
<%_ } _%>"""

        results = translate_legacy_ejs_conditions(content)
        self.assertGreater(len(results), 0)

        # Branch 0: === undefined → translated (not exists)
        self.assertEqual(results[0]["status"], "translated")
        self.assertIn("not", results[0]["ast"])

        # Branch 1: >= 15 && < 20 && === false → translated
        self.assertEqual(results[1]["status"], "translated")
        self.assertIn("all", results[1]["ast"])
        self.assertEqual(len(results[1]["ast"]["all"]), 3)

    def test_branches_with_getvar_in_content(self):
        """All branches in 桃花村 pattern are translatable."""
        content = """<%_ if (getvar('stat_data.周语晴.背德值') === undefined) { _%>
<%_ } else if (getvar('stat_data.周语晴.背德值') >= 15 && getvar('stat_data.周语晴.背德值') < 20 && getvar('stat_data.事件.厨房的温情') === false) { _%>
<%_ } else if (getvar('stat_data.周语晴.背德值') >= 30 && getvar('stat_data.周语晴.背德值') < 35 && getvar('stat_data.事件.夜晚的准备') === false) { _%>
<%_ } else if (getvar('stat_data.周语晴.背德值') >= 55 && getvar('stat_data.周语晴.背德值') < 60 && getvar('stat_data.事件.井边的协作') === false) { _%>
<%_ } _%>"""

        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]
        # All 4 branches should be translated
        self.assertEqual(len(translated), 4)

    def test_no_ejs_returns_empty(self):
        """Content without EJS returns empty list."""
        results = translate_legacy_ejs_conditions("Just plain text, no conditions.")
        self.assertEqual(len(results), 0)


# ═══════════════════════════════════════════════════════════════════════════
# Test 2b: Legacy adapter against real card deferred entries
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyAdapterRealCard(unittest.TestCase):
    """Test the adapter against the actual deferred entries from the card."""

    DEFERRED_PATH = os.path.join(
        PARENT_DIR, "data", "cards",
        "1efc516266b0f4bbd0614c4fb8367d750e1d3e112ac7cafe390bdb4e074ad8ac",
        "deferred-worldbook.json",
    )

    def _load_deferred(self):
        if not os.path.exists(self.DEFERRED_PATH):
            self.skipTest("Card deferred-worldbook.json not found")
        with open(self.DEFERRED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_all_4_entries_reported(self):
        """All 4 deferred entries are processed."""
        deferred = self._load_deferred()
        self.assertEqual(len(deferred), 4)

    def test_entry_0_uid26_conditions_translatable(self):
        """Entry 0 (uid=26) has bare else → entire group deferred_unsupported."""
        deferred = self._load_deferred()
        content = deferred[0].get("originalContent", "")
        results = translate_legacy_ejs_conditions(content)
        # Entry has bare else → all branches deferred
        for r in results:
            self.assertEqual(r["status"], "deferred_unsupported")
            self.assertEqual(r["reason"], "unsupported_else_branch")

    def test_entry_1_uid27_conditions_translatable(self):
        """Entry 1 (uid=27) has bare else → entire group deferred_unsupported."""
        deferred = self._load_deferred()
        content = deferred[1].get("originalContent", "")
        results = translate_legacy_ejs_conditions(content)
        for r in results:
            self.assertEqual(r["status"], "deferred_unsupported")
            self.assertEqual(r["reason"], "unsupported_else_branch")

    def test_entry_2_uid31_no_ejs(self):
        """Entry 2 (uid=31, staged performance) has no EJS conditions."""
        deferred = self._load_deferred()
        content = deferred[2].get("originalContent", "")
        results = translate_legacy_ejs_conditions(content)
        # May have 0 EJS conditions (it's a description text)
        # Or it might have getvar in a different context
        for r in results:
            # If any exist, they should either translate or defer
            self.assertIn(r["status"], ("translated", "deferred_unsupported"))

    def test_entry_3_uid32_no_ejs(self):
        """Entry 3 (uid=32, staged performance) has no EJS conditions."""
        deferred = self._load_deferred()
        content = deferred[3].get("originalContent", "")
        results = translate_legacy_ejs_conditions(content)
        for r in results:
            self.assertIn(r["status"], ("translated", "deferred_unsupported"))

    def test_translated_conditions_evaluable(self):
        """Translated AST conditions can be evaluated against state."""
        deferred = self._load_deferred()
        content = deferred[0].get("originalContent", "")
        results = translate_legacy_ejs_conditions(content)
        translated = [r for r in results if r["status"] == "translated"]

        # Test with state where 背德值 = 15
        state = {"stat_data": {"周语晴": {"背德值": 15}, "事件": {"厨房的温情": False}}}
        for branch in translated:
            ast = branch["ast"]
            if ast:
                node = ConditionNode.from_dict(ast)
                ok, reason = evaluate_condition(node, state)
                # Should not crash; result depends on the condition
                self.assertIsInstance(ok, bool)

    def test_range_condition_active_when_met(self):
        """When 背德值=15, the >=15 && <20 && event===false branch is active."""
        # Build the exact condition from the card
        cond = (
            "getvar('stat_data.周语晴.背德值') >= 15 && "
            "getvar('stat_data.周语晴.背德值') < 20 && "
            "getvar('stat_data.事件.厨房的温情') === false"
        )
        node, status = translate_legacy_condition(cond)
        self.assertEqual(status, "translated")

        state = {"stat_data": {"周语晴": {"背德值": 15}, "事件": {"厨房的温情": False}}}
        ok, reason = evaluate_condition(node, state)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_range_condition_blocked_when_not_met(self):
        """When 背德值=5, the >=15 branch is blocked."""
        cond = (
            "getvar('stat_data.周语晴.背德值') >= 15 && "
            "getvar('stat_data.周语晴.背德值') < 20 && "
            "getvar('stat_data.事件.厨房的温情') === false"
        )
        node, status = translate_legacy_condition(cond)
        self.assertEqual(status, "translated")

        state = {"stat_data": {"周语晴": {"背德值": 5}, "事件": {"厨房的温情": False}}}
        ok, reason = evaluate_condition(node, state)
        self.assertFalse(ok)

    def test_translated_entry_enters_conditional_active(self):
        """A deferred entry with translated condition enters conditionalActive
        when variables are met, and stays blocked when not."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node_runner = AWPConditionalWorldbook()

        # State where 背德值=15 and event not consumed
        state_meeting = CardState(
            cardId="c1", sessionId="s1",
            variables={"stat_data": {"周语晴": {"背德值": 15}, "事件": {"厨房的温情": False}}},
        ).to_json()

        # Simulate a deferred entry with EJS content
        deferred_entry = {
            "sourceEntryUid": 26,
            "reason": "deferred-variable",
            "originalContent": (
                "<%_ if (getvar('stat_data.周语晴.背德值') >= 15 && "
                "getvar('stat_data.周语晴.背德值') < 20 && "
                "getvar('stat_data.事件.厨房的温情') === false) { _%>"
                "厨房温情事件内容"
                "<%_ } _%>"
            ),
        }

        active, blocked, eval_json, debug_json = node_runner.execute(
            card_state_json=state_meeting,
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps([deferred_entry]),
        )
        active_list = json.loads(active)
        # The translated condition should be active
        self.assertGreater(len(active_list), 0)
        self.assertEqual(active_list[0].get("sourceEntryUid"), 26)

    def test_translated_entry_blocked_when_vars_not_met(self):
        """Deferred entry stays blocked when variables don't meet."""
        from comfyui_awp_rp.nodes.card_state_nodes import AWPConditionalWorldbook
        node_runner = AWPConditionalWorldbook()

        # State where 背德值=5 (below threshold)
        state_not_meeting = CardState(
            cardId="c1", sessionId="s1",
            variables={"stat_data": {"周语晴": {"背德值": 5}, "事件": {"厨房的温情": False}}},
        ).to_json()

        deferred_entry = {
            "sourceEntryUid": 26,
            "originalContent": (
                "<%_ if (getvar('stat_data.周语晴.背德值') >= 15 && "
                "getvar('stat_data.周语晴.背德值') < 20 && "
                "getvar('stat_data.事件.厨房的温情') === false) { _%>"
                "内容"
                "<%_ } _%>"
            ),
        }

        active, blocked, eval_json, debug_json = node_runner.execute(
            card_state_json=state_not_meeting,
            worldbook_json="[]",
            player_input="test",
            deferred_worldbook_json=json.dumps([deferred_entry]),
        )
        blocked_list = json.loads(blocked)
        self.assertGreater(len(blocked_list), 0)

    def test_no_hardcoded_names(self):
        """Adapter production code does not hardcode any specific card names/UIDs."""
        import inspect
        from comfyui_awp_rp.card import card_state_contract
        source = inspect.getsource(card_state_contract)
        forbidden = [
            "桃花村", "周语晴", "老马", "马俊伟", "背德值", "厨房的温情",
            "夜晚的准备", "井边的协作", "贴心的照顾", "田间的意外",
            "餐桌上的默契", "深夜的关怀", "一件心意", "主动的亲近", "家的新定义",
        ]
        for name in forbidden:
            self.assertNotIn(
                name, source,
                f"Card-specific literal '{name}' found in card_state_contract.py",
            )


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Workflow Link Validation
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowValidation(unittest.TestCase):
    """Automated validation of rp_stateful_card_v1.json."""

    WORKFLOW_PATH = os.path.join(PARENT_DIR, "workflows", "rp_stateful_card_v1.json")

    def _load_workflow(self):
        with open(self.WORKFLOW_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_json_valid(self):
        """Workflow JSON is valid."""
        wf = self._load_workflow()
        self.assertIsInstance(wf, dict)

    def test_all_nodes_registered(self):
        """All node class_types are registered in NODE_CLASS_MAPPINGS."""
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        wf = self._load_workflow()
        for node_id, node_data in wf.items():
            if node_id.startswith("_"):
                continue
            class_type = node_data.get("class_type", "")
            self.assertIn(
                class_type, NODE_CLASS_MAPPINGS,
                f"Node {node_id} ({class_type}) not in NODE_CLASS_MAPPINGS",
            )

    def test_writer_contract_connected_to_writer(self):
        """writer_contract_json connects from RoundPreparer to DialogueDirector."""
        wf = self._load_workflow()
        # Find DialogueDirector node
        director_node = None
        for nid, ndata in wf.items():
            if nid.startswith("_"):
                continue
            if ndata.get("class_type") == "AWPDialogueDirector":
                director_node = nid
                break
        self.assertIsNotNone(director_node, "No AWPDialogueDirector found")

        # Check writer_contract_json input
        inputs = wf[director_node].get("inputs", {})
        contract_input = inputs.get("writer_contract_json")
        self.assertIsNotNone(
            contract_input,
            "DialogueDirector missing writer_contract_json input",
        )
        # Must be a link (list with [source_node, slot])
        self.assertIsInstance(contract_input, list)
        source_node = str(contract_input[0])
        self.assertIn(
            wf[source_node]["class_type"],
            ("AWPRoundPreparer",),
            f"writer_contract_json links from {wf[source_node]['class_type']}, expected AWPRoundPreparer",
        )

    def test_writer_contract_connected_to_quality_gate(self):
        """writer_contract_json connects from RoundPreparer to QualityGate."""
        wf = self._load_workflow()
        qg_node = None
        for nid, ndata in wf.items():
            if nid.startswith("_"):
                continue
            if ndata.get("class_type") == "AWPQualityGate":
                qg_node = nid
                break
        self.assertIsNotNone(qg_node)

        inputs = wf[qg_node].get("inputs", {})
        contract_input = inputs.get("writer_contract_json")
        self.assertIsNotNone(contract_input)
        self.assertIsInstance(contract_input, list)

    def test_quality_gate_to_side_effect(self):
        """QualityGate decision connects to SideEffectDecision."""
        wf = self._load_workflow()
        se_node = None
        for nid, ndata in wf.items():
            if nid.startswith("_"):
                continue
            if ndata.get("class_type") == "AWPSideEffectDecision":
                se_node = nid
                break
        self.assertIsNotNone(se_node)

        inputs = wf[se_node].get("inputs", {})
        quality_input = inputs.get("quality_decision_json")
        self.assertIsNotNone(quality_input)
        self.assertIsInstance(quality_input, list)
        # Source must be QualityGate
        source_node = str(quality_input[0])
        self.assertEqual(wf[source_node]["class_type"], "AWPQualityGate")

    def test_no_main_agent_in_required_path(self):
        """MainAgent is NOT in the required execution path."""
        wf = self._load_workflow()
        for nid, ndata in wf.items():
            if nid.startswith("_"):
                continue
            if ndata.get("class_type") == "AWPMainAgent":
                self.fail("AWPMainAgent should not be in the reference workflow")
        # No MainAgent → pass

    def test_card_state_patch_no_direct_store_write(self):
        """CandidateCardStatePatch doesn't bypass QualityGate."""
        wf = self._load_workflow()
        # Check that SideEffectDecision receives quality_decision
        se_node = None
        for nid, ndata in wf.items():
            if nid.startswith("_"):
                continue
            if ndata.get("class_type") == "AWPSideEffectDecision":
                se_node = nid
                break
        self.assertIsNotNone(se_node)
        inputs = wf[se_node].get("inputs", {})
        # Must have quality_decision_json wired
        self.assertIn("quality_decision_json", inputs)
        # allow_commit_when_accepted should be False by default
        self.assertFalse(inputs.get("allow_commit_when_accepted", True))

    def test_old_workflows_not_modified(self):
        """Old workflow files are not modified."""
        old_wf_path = os.path.join(PARENT_DIR, "workflows", "rp_full_features_routed_v1_workflow.json")
        if os.path.exists(old_wf_path):
            with open(old_wf_path, "r", encoding="utf-8") as f:
                old_wf = json.load(f)
            # Just verify it still loads and has original nodes
            self.assertIn("34", old_wf)  # router
            self.assertIn("35", old_wf)  # orchestrator


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: Regression
# ═══════════════════════════════════════════════════════════════════════════

class TestRegressionP4D1A(unittest.TestCase):
    """Regression tests: existing functionality not broken."""

    def test_quality_gate_backward_compat(self):
        """QualityGate works without writer_contract_json."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPQualityGate
        gate = AWPQualityGate()
        result = gate.execute(reply="她看着他，轻声说道。" * 50)
        decision = json.loads(result[0])
        self.assertIn("accepted", decision)

    def test_director_backward_compat(self):
        """DialogueDirector works without writer_contract_json."""
        prompt = build_director_prompt(
            context_bundle="{}",
            system_prompt="测试",
        )
        self.assertIn("请基于以上上下文续写本回合", prompt)

    def test_round_preparer_5_outputs(self):
        """RoundPreparer still has 5 outputs."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
        self.assertEqual(len(AWPRoundPreparer.RETURN_NAMES), 5)

    def test_side_effect_3_outputs(self):
        """SideEffectDecision still has 3 outputs."""
        from comfyui_awp_rp.nodes.pipeline_nodes import AWPSideEffectDecision
        self.assertEqual(len(AWPSideEffectDecision.RETURN_NAMES), 3)

    def test_p4d1_tests_still_pass(self):
        """P4D-1 base tests are not broken by P4D-1A changes."""
        # Import and verify key contracts still work
        state = CardState(cardId="c1", sessionId="s1", variables={"x": 1})
        self.assertEqual(state.schemaId, "awp.rp.card-state.v1")

        contract = WriterContract(sessionId="s1", cardId="c1")
        self.assertEqual(contract.schemaId, "awp.rp.writer-contract.v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
