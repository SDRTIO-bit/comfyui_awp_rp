"""Behavior tests for the ComfyUI-native RP pipeline nodes."""

import json
import os
import base64
import struct
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


from comfyui_awp_rp.core.config import Config
from comfyui_awp_rp.core.types import RetrievalDocument
from comfyui_awp_rp.card.import_card import load_card_json_from_file
from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
from comfyui_awp_rp.nodes.worldbook_node import AWPWorldbookList
from comfyui_awp_rp.nodes.retriever_node import AWPRetriever
from comfyui_awp_rp.retrieval.scorer import RetrievalConfig, RetrievalScorer
from comfyui_awp_rp.rp_pipeline import (
    apply_quality_gate,
    apply_context_mode,
    build_context_bundle,
    build_side_effect_decision,
    parse_rp_input,
    propose_turn_patches,
    render_final_output,
)


class RpPipelineBehaviorTests(unittest.TestCase):
    def test_new_nodes_are_registered(self):
        expected = {
            "AWPTextInput",
            "AWPJsonInput",
            "AWPTextOutput",
            "AWPJsonOutput",
            "AWPWorldbookList",
            "AWPInputParser",
            "AWPContextAssembler",
            "AWPDialogueDirector",
            "AWPQualityGate",
            "AWPPatchProposal",
            "AWPOutputRenderer",
            "AWPSideEffectDecision",
        }

        self.assertTrue(expected.issubset(set(NODE_CLASS_MAPPINGS)))

    def test_pipeline_nodes_expose_connectable_inputs(self):
        parser_inputs = NODE_CLASS_MAPPINGS["AWPInputParser"].INPUT_TYPES()
        assembler_inputs = NODE_CLASS_MAPPINGS["AWPContextAssembler"].INPUT_TYPES()

        self.assertTrue(parser_inputs["required"]["user_input"][1]["forceInput"])
        self.assertTrue(parser_inputs["optional"]["known_entities_json"][1]["forceInput"])
        self.assertTrue(assembler_inputs["required"]["parsed_input_json"][1]["forceInput"])
        self.assertTrue(assembler_inputs["optional"]["worldbook_context_json"][1]["forceInput"])

    def test_context_mode_can_drop_memory_or_all_context(self):
        parsed = parse_rp_input("“继续说。”", known_entities=[])
        bundle = build_context_bundle(
            parsed,
            character_profile_json=json.dumps({"name": "艾琳"}, ensure_ascii=False),
            scene_state_json=json.dumps({"location": "旧宅大厅"}, ensure_ascii=False),
            worldbook_context_json=json.dumps([{"id": "wb_1", "content": "世界书"}], ensure_ascii=False),
            memory_context_json=json.dumps([{"id": "mem_1", "content": "长期记忆"}], ensure_ascii=False),
        )

        no_memory = apply_context_mode(bundle, "no_memory")
        stateless = apply_context_mode(bundle, "stateless_no_context")

        self.assertNotIn("memorySection", no_memory["sections"])
        self.assertIn("worldbookSection", no_memory["sections"])
        self.assertNotIn("worldbookSection", stateless["sections"])
        self.assertNotIn("sceneStateSection", stateless["sections"])
        self.assertIn("rawUserInputSection", stateless["sections"])

    def test_parser_keeps_structured_player_input(self):
        parsed = parse_rp_input(
            "我看向艾琳，低声说：“别靠近那扇门。” *握紧银钥匙* 然后调查大厅里的血迹。",
            known_entities=[
                {
                    "entityId": "char_erin",
                    "entryId": "wb_erin",
                    "name": "艾琳",
                    "aliases": ["Erin"],
                    "category": "character",
                }
            ],
        )

        self.assertEqual(parsed["version"], "parsed-rp-input-v1")
        self.assertEqual(parsed["dialogues"][0]["speakerEntityId"], "player")
        self.assertEqual(parsed["dialogues"][0]["text"], "别靠近那扇门。")
        self.assertEqual(parsed["actions"][0]["actorEntityId"], "player")
        self.assertIn("握紧银钥匙", parsed["actions"][0]["action"])
        self.assertEqual(parsed["mentions"][0]["entityId"], "char_erin")
        self.assertIn("investigate", [item["type"] for item in parsed["intents"]])

    def test_context_assembler_outputs_prompt_document_and_used_context(self):
        parsed = parse_rp_input("“继续说。” *靠近门边*", known_entities=[])
        bundle = build_context_bundle(
            parsed,
            character_profile_json=json.dumps({"name": "艾琳", "personality": "谨慎"}, ensure_ascii=False),
            scene_state_json=json.dumps({"location": "旧宅大厅", "time": "深夜"}, ensure_ascii=False),
            worldbook_context_json=json.dumps(
                [
                    {"id": "wb_door", "title": "封印之门", "content": "门后有低语声。"},
                    {"id": "wb_erin", "title": "艾琳", "content": "她害怕黑暗。"},
                ],
                ensure_ascii=False,
            ),
            memory_context_json=json.dumps(
                [{"id": "mem_1", "content": "玩家之前答应保护艾琳。"}],
                ensure_ascii=False,
            ),
            preset_sections_json=json.dumps(
                [{"id": "core-no-player-control", "content": "不要替玩家行动。", "priority": 100}],
                ensure_ascii=False,
            ),
            target_tokens=1200,
        )

        self.assertEqual(bundle["version"], "awp.comfy.rp-context-bundle.v1")
        self.assertIn("rawUserInputSection", bundle["sections"])
        self.assertIn("dialoguesSection", bundle["sections"])
        self.assertIn("characterProfileSection", bundle["sections"])
        self.assertIn("## User Input (raw)", bundle["prompt"])
        self.assertEqual(bundle["usedContext"]["usedWorldbookEntries"][0]["id"], "wb_door")
        self.assertEqual(bundle["usedContext"]["recalledMemories"][0]["id"], "mem_1")

    def test_patch_proposals_are_pending_and_do_not_commit(self):
        parsed = parse_rp_input("“我会记住这个约定。”", known_entities=[])
        patches = propose_turn_patches(
            session_id="session-a",
            parsed_input=parsed,
            reply="艾琳点头，把这个约定郑重地记在心里。",
            character_id="char_erin",
            scene_id="scene_hall",
        )

        self.assertEqual(patches["candidateMemoryPatch"]["commitPolicy"], "pending")
        self.assertEqual(patches["candidateStatePatch"]["commitPolicy"], "pending")
        self.assertFalse(patches["candidateMemoryPatch"]["autoCommit"])
        self.assertFalse(patches["candidateStatePatch"]["autoCommit"])
        self.assertGreaterEqual(len(patches["candidateMemoryPatch"]["candidates"]), 1)

    def test_quality_gate_rejects_player_agency_and_format_leaks(self):
        decision = apply_quality_gate("```json\n{\"你决定逃走\": true}\n```")

        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("player-agency", decision["failedChecks"])
        self.assertIn("format", decision["failedChecks"])
        self.assertTrue(decision["revisionInstruction"])

    def test_renderer_includes_side_effect_denials_and_debug_log(self):
        parsed = parse_rp_input("“继续。”", known_entities=[])
        patches = propose_turn_patches("session-a", parsed, "艾琳继续讲述。")
        quality = apply_quality_gate("艾琳继续讲述。")
        side_effects = build_side_effect_decision(quality, patches)
        rendered = render_final_output(
            reply="艾琳继续讲述。",
            context_bundle={"usedContext": {"usedWorldbookEntries": [], "recalledMemories": [], "usedSceneState": {}}},
            candidate_state_patch=patches["candidateStatePatch"],
            candidate_memory_patch=patches["candidateMemoryPatch"],
            quality_decision=quality,
            side_effect_decision=side_effects,
        )

        self.assertEqual(rendered["narrative"], "艾琳继续讲述。")
        self.assertFalse(rendered["sideEffectDecision"]["allowMemoryCommit"])
        self.assertFalse(rendered["sideEffectDecision"]["allowStateCommit"])
        self.assertEqual(rendered["candidateMemoryPatch"]["commitPolicy"], "pending")
        self.assertGreaterEqual(len(rendered["debugLog"]), 1)

    def test_retriever_does_not_return_zero_score_hits_by_default(self):
        docs = [
            RetrievalDocument(id="a", title="月亮", content="银色月光照在水面。"),
            RetrievalDocument(id="b", title="森林", content="树林很安静。"),
        ]
        result = RetrievalScorer(RetrievalConfig(strategy="keyword")).retrieve("完全无关的词", docs)

        self.assertEqual(result.hits, [])

        text, data = AWPRetriever().execute("完全无关的词", json.dumps([doc.__dict__ for doc in docs], ensure_ascii=False))
        self.assertIn("No matches", text)
        self.assertEqual(json.loads(data), [])

    def test_config_loads_env_provider_without_saving_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "RP_PROVIDER": "deepseek",
                    "RP_MODEL": "deepseek-v4-flash",
                    "DEEPSEEK_API_KEY": "test-secret",
                },
                clear=False,
            ):
                config = Config.load(data_dir=tmp)

        self.assertIn("deepseek", config.providers)
        self.assertEqual(config.default_provider_id, "deepseek")
        self.assertEqual(config.providers["deepseek"].default_model, "deepseek-v4-flash")
        self.assertEqual(config.providers["deepseek"].api_key, "test-secret")

    def test_card_json_can_be_loaded_from_json_and_png_file(self):
        card = {
            "spec": "chara_card_v3",
            "data": {
                "name": "艾琳",
                "description": "谨慎的调查员",
                "first_mes": "雨声里，艾琳抬起头。",
                "alternate_greetings": [],
                "character_book": {"entries": []},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "erin.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(card, f, ensure_ascii=False)

            png_path = os.path.join(tmp, "erin.png")
            _write_card_png(png_path, card)

            self.assertEqual(load_card_json_from_file(json_path)["data"]["name"], "艾琳")
            self.assertEqual(load_card_json_from_file(png_path)["data"]["name"], "艾琳")

    def test_worldbook_list_renders_activation_switch_and_keywords(self):
        worldbook_json = json.dumps(
            [
                {
                    "id": "wb_1",
                    "title": "旧宅大厅",
                    "content": "大厅里有封印之门。",
                    "tags": ["旧宅", "门"],
                    "priority": 80,
                    "metadata": {"constant": False, "selective": True, "enabled": True},
                },
                {
                    "id": "wb_2",
                    "title": "禁用条目",
                    "content": "不应显示",
                    "tags": ["隐藏"],
                    "metadata": {"enabled": False},
                },
            ],
            ensure_ascii=False,
        )

        list_text, list_json = AWPWorldbookList().execute(worldbook_json, enabled_only=True)

        self.assertIn("[ON] 关键词", list_text)
        self.assertIn("旧宅, 门", list_text)
        rows = json.loads(list_json)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["enabled"])


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def _write_card_png(path: str, card: dict):
    payload = base64.b64encode(json.dumps(card, ensure_ascii=False).encode("utf-8"))
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    png += _png_chunk(b"tEXt", b"chara\x00" + payload)
    png += _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
    png += _png_chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    unittest.main()
