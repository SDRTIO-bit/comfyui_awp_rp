import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "server"))

import workflow_runner  # noqa: E402


class WorkflowRunnerConversionTests(unittest.TestCase):
    def test_api_prompt_workflow_is_preserved(self):
        workflow = workflow_runner.load_workflow("rp_complete_api_workflow.json")

        prompt = workflow_runner.convert_to_api_format(workflow)

        self.assertEqual(len(prompt["prompt"]), len(workflow))
        self.assertEqual(prompt["prompt"]["13"]["class_type"], "AWPMainAgent")
        self.assertIn("provider", prompt["prompt"]["13"]["inputs"])

    def test_api_prompt_workflow_can_be_analyzed(self):
        analysis = workflow_runner.analyze_workflow("rp_complete_api_workflow.json")

        self.assertEqual(analysis["node_count"], 23)
        roles = {item["role"] for item in analysis["roles"]}
        self.assertIn("user_input", roles)
        self.assertIn("generator", roles)

    def test_save_format_keeps_widget_values_for_linked_nodes(self):
        workflow = workflow_runner.load_workflow("rp_full_node_workflow.json")

        prompt = workflow_runner.convert_to_api_format(workflow)["prompt"]

        self.assertEqual(prompt["8"]["inputs"]["card_id"], ["7", 0])
        self.assertEqual(prompt["8"]["inputs"]["mode"], "list")
        self.assertEqual(prompt["13"]["inputs"]["context_bundle_json"], ["12", 1])
        self.assertEqual(prompt["13"]["inputs"]["provider"], "deepseek")
        self.assertEqual(prompt["13"]["inputs"]["model"], "deepseek-chat")
        self.assertEqual(prompt["20"]["inputs"]["project_id"], ["2", 0])
        self.assertEqual(prompt["20"]["inputs"]["name"], "桃花村RP")
        self.assertEqual(prompt["20"]["inputs"]["project_type"], "rp")
        self.assertEqual(prompt["20"]["inputs"]["snapshot_type"], "turn")

    def test_api_prompt_role_injections_use_input_overrides(self):
        workflow = workflow_runner.load_workflow("rp_complete_api_workflow.json")
        analysis = workflow_runner.analyze_workflow("rp_complete_api_workflow.json")

        widgets, overrides = workflow_runner._roles_to_injections(
            workflow,
            {
                "user_input": "hello",
                "session_id": "session-x",
                "generator": {"provider": "deepseek", "model": "deepseek-chat"},
            },
            analysis,
        )

        self.assertEqual(widgets, {})
        self.assertEqual(overrides["1"]["text"], "hello")
        self.assertEqual(overrides["2"]["text"], "session-x")
        self.assertEqual(overrides["13"]["provider"], "deepseek")

    def test_load_workflow_rejects_path_traversal(self):
        self.assertIsNone(workflow_runner.load_workflow("../.env.example"))

    def test_history_error_is_reported_as_failure(self):
        history_entry = {
            "status": {
                "status_str": "error",
                "messages": [["execution_error", {"exception_message": "node exploded"}]],
            },
            "outputs": {},
        }

        self.assertEqual(
            workflow_runner._history_error(history_entry),
            "node exploded",
        )

    def test_output_nodes_return_ui_payload_for_history(self):
        from comfyui_awp_rp.nodes.input_nodes import AWPTextOutput

        result = AWPTextOutput().execute("hello", "final")

        self.assertEqual(result["result"], ("hello",))
        self.assertEqual(result["ui"]["text"], ["hello"])
        self.assertEqual(result["ui"]["label"], ["final"])


if __name__ == "__main__":
    unittest.main()
