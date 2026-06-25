"""Debug: check what prompt format we're sending to ComfyUI."""
import json, sys
sys.path.insert(0, ".")
from workflow_runner import load_workflow, convert_to_api_format, inject_inputs

wf = load_workflow("rp_full_node_workflow.json")
wf = inject_inputs(wf, {"1": ["Hello traveler"]})
prompt = convert_to_api_format(wf)

for nid in sorted(prompt["prompt"].keys(), key=int)[:8]:
    node = prompt["prompt"][nid]
    print(f"Node {nid} ({node['class_type']}): {json.dumps(node['inputs'], ensure_ascii=False)[:200]}")

print(f"\nTotal nodes: {len(prompt['prompt'])}")
print(f"Prompt size: {len(json.dumps(prompt, ensure_ascii=False))} chars")
