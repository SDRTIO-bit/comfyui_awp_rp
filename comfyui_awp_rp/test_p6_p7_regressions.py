"""Regression tests for P6/P7 runtime paths."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


from comfyui_awp_rp.card.import_card import CardImporter
from comfyui_awp_rp.core.llm_router import LlmRouter, ProviderRegistry
from comfyui_awp_rp.core.types import (
    LlmCompletionResult,
    LlmTokenUsage,
    LlmToolCall,
    ProviderConfig,
)
from comfyui_awp_rp.nodes.main_agent import AWPMainAgent
from comfyui_awp_rp.nodes.pipeline_nodes import AWPRoundPreparer
from comfyui_awp_rp.nodes.retriever_node import AWPRetriever
from comfyui_awp_rp.retrieval.vector_store import VectorStore
from comfyui_awp_rp.tools.builtin.delegate_tool import _run_sub_agent
from comfyui_awp_rp.tools.tool_executor import should_parallelize


def _router() -> LlmRouter:
    registry = ProviderRegistry(default_provider_id="test")
    registry.register(
        ProviderConfig(
            provider_id="test",
            api_key="secret",
            base_url="https://example.invalid/v1",
            default_model="test-model",
            models=[],
        )
    )
    return LlmRouter(registry)


class P6P7RegressionTests(unittest.TestCase):
    def test_complete_with_tools_returns_result_provider_and_model(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "id": "req_1",
                    "choices": [
                        {
                            "message": {"content": "hello"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                }

        with patch("comfyui_awp_rp.core.llm_router.requests.post", return_value=FakeResponse()):
            result, provider_id, model = _router().complete_with_tools(
                {"provider": "test", "model": "override-model"},
                [{"role": "user", "content": "hi"}],
            )

        self.assertIsInstance(result, LlmCompletionResult)
        self.assertEqual(result.text, "hello")
        self.assertEqual(provider_id, "test")
        self.assertEqual(model, "override-model")

    def test_main_agent_loop_accepts_router_tuple(self):
        def fake_complete_with_tools(self, *args, **kwargs):
            return (
                LlmCompletionResult(
                    text="final reply",
                    token_usage=LlmTokenUsage(input=1, output=2),
                    finish_reason="stop",
                ),
                "deepseek",
                "deepseek-chat",
            )

        with patch("comfyui_awp_rp.core.llm_router.LlmRouter.complete_with_tools", fake_complete_with_tools):
            reply, _ctx, meta, _vars, _changes = AWPMainAgent().execute(
                "hi",
                "p6p7-agent-loop-test",
                enable_agent_loop=True,
                record_session=False,
                provider="deepseek",
                model="deepseek-chat",
            )

        self.assertEqual(reply, "final reply")
        self.assertEqual(json.loads(meta)["agent_loop"], True)

    def test_complete_stream_uses_public_adapter_fields_and_yields_dicts(self):
        class FakeStreamResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=False):
                lines = [
                    'data: {"choices":[{"delta":{"content":"hel"},"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
                    "data: [DONE]",
                ]
                return iter(lines)

        posts = []

        def fake_post(url, headers=None, **kwargs):
            posts.append((url, headers, kwargs))
            return FakeStreamResponse()

        with patch("comfyui_awp_rp.core.llm_router.requests.post", fake_post):
            chunks = list(
                _router().complete_stream(
                    {"provider": "test", "model": "stream-model"},
                    [{"role": "user", "content": "hi"}],
                )
            )

        self.assertEqual(posts[0][0], "https://example.invalid/v1/chat/completions")
        self.assertEqual(posts[0][1]["Authorization"], "Bearer secret")
        self.assertTrue(all(isinstance(chunk, dict) for chunk in chunks))
        self.assertEqual([chunk["token"] for chunk in chunks[:2]], ["hel", "lo"])
        self.assertEqual(chunks[-1]["finish_reason"], "stop")

    def test_should_parallelize_blocks_dependencies_in_either_order(self):
        analysis = LlmToolCall(id="1", name="story_plan_analysis_task", arguments="{}")
        build = LlmToolCall(id="2", name="story_plan_build_context", arguments="{}")

        self.assertFalse(should_parallelize([analysis, build]))
        self.assertFalse(should_parallelize([build, analysis]))

    def test_vector_store_fallback_delete_removes_indexed_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = VectorStore(tmp, "test_collection")
            store.index(
                [
                    {"id": "a", "title": "Moon", "content": "silver moon over water"},
                    {"id": "b", "title": "Forest", "content": "quiet trees"},
                ]
            )

            self.assertEqual(store.delete(["a"]), 1)
            self.assertEqual(store.count(), 1)
            self.assertEqual(store.search("moon water", top_k=2, min_score=0.01), [])

    def test_card_import_saves_detected_card_structure(self):
        store = Mock()
        store.load_card.return_value = None
        card = {
            "spec": "chara_card_v3",
            "data": {
                "name": "Structured",
                "description": "Phase 1: guarded.\nPhase 2: trusting.",
                "first_mes": "hello",
                "alternate_greetings": [],
                "character_book": {"entries": []},
            },
        }

        CardImporter(store=store).import_card(card)

        report = store.save_card.call_args.kwargs["report"]
        manifest = store.save_card.call_args.kwargs["manifest"]
        self.assertTrue(report["card_structure"]["has_structure"])
        self.assertEqual(report["card_structure"]["phases"][0]["phase"], "1")
        self.assertTrue(manifest["has_structure"])

    def test_new_workflow_templates_are_comfyui_import_shape(self):
        root = Path(__file__).resolve().parent.parent
        for path in [
            root / "workflows" / "rp_agent_full.json",
            root / "workflows" / "novel_writing.json",
        ]:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("nodes", data)
            self.assertNotIn("edges", data)
            self.assertTrue(data)
            first = next(iter(data.values()))
            self.assertIn("class_type", first)
            self.assertIn("inputs", first)

    def test_main_agent_invalid_profile_returns_all_declared_outputs(self):
        result = AWPMainAgent().execute(
            "hello",
            "bad-profile-test",
            profile="missing-profile",
            record_session=False,
        )

        self.assertEqual(len(result), len(AWPMainAgent.RETURN_TYPES))
        self.assertEqual(json.loads(result[2])["error"], "profile_not_found")

    def test_round_preparer_applies_variable_injection_rules(self):
        variables = {"world": {"hooks": "Moon Gate, River Oath"}}
        worldbook = [
            {
                "id": "wb_moon",
                "keyword": "Moon Gate",
                "title": "Moon Gate",
                "one_liner": "A sealed gate that answers moonlight.",
                "section": "## Moon Gate\nA sealed gate that answers moonlight.",
            },
            {
                "id": "wb_oath",
                "keyword": "River Oath",
                "title": "River Oath",
                "one_liner": "A vow witnessed by the black river.",
                "section": "## River Oath\nA vow witnessed by the black river.",
            },
        ]
        rules = [{"source_path": "world.hooks", "split_pattern": "[,\\n]+", "prefix": ""}]

        _rp = AWPRoundPreparer().execute(
            "I inspect the altar.",
            "injection-test",
            current_variables=json.dumps(variables),
            worldbook_index=json.dumps(worldbook),
            injection_rules_json=json.dumps(rules),
            top_worldbook=3,
        )
        context, matches_json, _checklist, budget_json = _rp[0], _rp[1], _rp[2], _rp[3]

        matches = json.loads(matches_json)
        self.assertEqual(matches[0]["keyword"], "Moon Gate")
        self.assertEqual(matches[0]["source"], "injection_rule")
        self.assertIn("Worldbook: Moon Gate [injection-rule", context)
        self.assertEqual(json.loads(budget_json)["injection_matches"], 2)

    def test_round_preparer_injects_story_contract_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            story_dir = Path(tmp) / ".story-system"
            story_dir.mkdir()
            (story_dir / "MASTER_SETTING.json").write_text(
                json.dumps({"forbidden_zones": ["No player control"]}),
                encoding="utf-8",
            )
            (story_dir / "volume_001.json").write_text(
                json.dumps({"pacing_strategy": "Keep the scene tense."}),
                encoding="utf-8",
            )
            (story_dir / "chapter_0001.json").write_text(
                json.dumps({
                    "chapter_directive": {
                        "goal": "Force the shrine secret into the open.",
                        "time_anchor": "Midnight",
                    },
                    "must_cover_nodes": ["The bell rings once."],
                }),
                encoding="utf-8",
            )

            _rp = AWPRoundPreparer().execute(
                "I wait by the shrine.",
                "contract-test",
                project_root=tmp,
                chapter_num=1,
                story_genre="xianxia",
            )
            context, _matches, _checklist, budget_json = _rp[0], _rp[1], _rp[2], _rp[3]

        self.assertIn("## Story Contract", context)
        self.assertIn("Force the shrine secret into the open.", context)
        self.assertIn("Keep the scene tense.", context)
        self.assertIn("The bell rings once.", context)
        self.assertEqual(json.loads(budget_json)["story_contract_loaded"], True)

    def test_retriever_embedding_strategy_uses_vector_store(self):
        fake_store = Mock()
        fake_store.index.return_value = 1
        fake_store.search.return_value = [
            {
                "id": "doc_1",
                "content": "Moon Gate opens only under silver light.",
                "score": 0.91,
                "metadata": {"title": "Moon Gate", "type": "lore"},
            }
        ]

        with patch("comfyui_awp_rp.retrieval.vector_store.VectorStore", return_value=fake_store):
            text, data = AWPRetriever().execute(
                "moon gate",
                json.dumps([
                    {
                        "id": "doc_1",
                        "title": "Moon Gate",
                        "content": "Moon Gate opens only under silver light.",
                        "type": "lore",
                    }
                ]),
                strategy="embedding",
            )

        fake_store.index.assert_called_once()
        fake_store.search.assert_called_once()
        self.assertIn("Moon Gate", text)
        self.assertEqual(json.loads(data)[0]["id"], "doc_1")

    def test_delegate_sub_agent_uses_profile_defaults_when_overrides_empty(self):
        captured: list[dict] = []

        def fake_complete_with_tools(self, node_config, messages, tools=None, tool_choice=None):
            captured.append(node_config)
            return (
                LlmCompletionResult(
                    text='{"issues":[],"dimension_results":[]}',
                    token_usage=LlmTokenUsage(input=1, output=1),
                    finish_reason="stop",
                ),
                node_config["provider"],
                node_config.get("model") or "deepseek-chat",
            )

        with patch("comfyui_awp_rp.core.llm_router.LlmRouter.complete_with_tools", fake_complete_with_tools):
            _run_sub_agent(
                profile_id="rp-critic",
                task="review this reply",
                provider="deepseek",
                model="",
                temperature=None,
                max_tokens=None,
            )

        self.assertEqual(captured[0]["model"], "")
        self.assertEqual(captured[0]["temperature"], 0.2)
        self.assertEqual(captured[0]["max_tokens"], 1024)

    def test_main_agent_only_adds_action_options_for_rp_profiles(self):
        captured_messages: list[list[dict]] = []

        def fake_complete_with_tools(self, node_config, messages, tools=None, tool_choice=None):
            captured_messages.append(messages)
            return (
                LlmCompletionResult(
                    text="chapter text",
                    token_usage=LlmTokenUsage(input=1, output=1),
                    finish_reason="stop",
                ),
                node_config["provider"],
                node_config.get("model") or "deepseek-chat",
            )

        with patch("comfyui_awp_rp.core.llm_router.LlmRouter.complete_with_tools", fake_complete_with_tools):
            AWPMainAgent().execute(
                "Write the next chapter.",
                "novel-options-test",
                profile="novel-long-writer",
                enable_agent_loop=True,
                record_session=False,
                provider="deepseek",
                model="deepseek-chat",
            )

        system_text = captured_messages[0][0]["content"]
        self.assertNotIn("## 行动选项", system_text)

    def test_mvu_engine_selftest_is_safe_under_cp936_stdout(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp936"
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "mvu" / "engine.py")],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))

    def test_no_python_311_only_datetime_utc_imports(self):
        root = Path(__file__).resolve().parent
        bad_import = "from datetime import " + "UTC"
        bad_attribute = "datetime." + "UTC"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if bad_import in text or bad_attribute in text:
                offenders.append(str(path.relative_to(root.parent)))

        self.assertEqual(offenders, [])

    def test_full_coverage_api_workflow_covers_most_nodes_and_rp_path(self):
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS

        root = Path(__file__).resolve().parent.parent
        path = root / "workflows" / "rp_full_coverage_api_workflow.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("nodes", data)
        self.assertNotIn("links", data)
        class_types = {node["class_type"] for node in data.values()}
        # P4D-1 added AWPCardStateInit + AWPConditionalWorldbook (optional, not in legacy API workflow)
        self.assertGreaterEqual(len(class_types), len(NODE_CLASS_MAPPINGS) - 5)
        for required in [
            "AWPTextInput",
            "AWPCardImport",
            "AWPRoundPreparer",
            "AWPMainAgent",
            "AWPMVUNode",
            "AWPQualityGate",
            "AWPOutputRenderer",
        ]:
            self.assertIn(required, class_types)

        main_agent = next(node for node in data.values() if node["class_type"] == "AWPMainAgent")
        self.assertEqual(main_agent["inputs"]["user_input"], ["17", 0])


if __name__ == "__main__":
    unittest.main()
