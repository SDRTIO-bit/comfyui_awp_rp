"""
Workflow Runner — bridge between frontend and ComfyUI.

Scans workflow JSON files, discovers input/output nodes,
and proxies execution to ComfyUI's prompt API.
"""
import http.server
import json
import os
import re
import sys
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"
PORT = int(os.environ.get("RUNNER_PORT", "8765"))


def list_workflows() -> list[dict]:
    """List available workflow files with metadata."""
    workflows = []
    for f in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            nodes = wf.get("nodes", [])
            links = wf.get("links", [])

            inputs = _discover_inputs(nodes)
            outputs = _discover_outputs(nodes, links)

            workflows.append({
                "filename": f.name,
                "node_count": len(nodes),
                "link_count": len(links),
                "inputs": inputs,
                "outputs": outputs,
            })
        except Exception:
            pass
    return workflows


def _discover_inputs(nodes: list[dict]) -> list[dict]:
    """Find input nodes: no linked inputs, have widgets_values."""
    result = []
    for node in nodes:
        # Check: does this node have any upstream links?
        inputs = node.get("inputs") or []
        has_upstream = any(i.get("link") is not None for i in inputs)
        if has_upstream:
            continue

        widgets = node.get("widgets_values") or []
        if not widgets:
            continue

        ntype = node.get("type", "Unknown")
        # Build field definitions
        fields = []
        for idx, val in enumerate(widgets):
            if isinstance(val, bool):
                fields.append({"index": idx, "label": f"{ntype} #{idx+1}", "type": "bool", "default": val})
            elif isinstance(val, (int, float)):
                fields.append({"index": idx, "label": f"{ntype} #{idx+1}", "type": "number", "default": val})
            else:
                # Guess field name from nearby info
                label = _guess_label(node, idx)
                fields.append({"index": idx, "label": label, "type": "text", "default": str(val)})

        result.append({
            "node_id": node["id"],
            "type": node.get("type", "Unknown"),
            "title": node.get("title", ""),
            "fields": fields,
        })
    return result


def _discover_outputs(nodes: list[dict], links: list[dict]) -> list[dict]:
    """Find output nodes: no downstream links (terminal)."""
    # Build set of node IDs that have outgoing links
    has_outgoing = set()
    for link in links:
        origin_id = link[1]  # links: [id, from_node, from_slot, to_node, to_slot, type]
        has_outgoing.add(origin_id)

    result = []
    for node in nodes:
        if node["id"] not in has_outgoing:
            outputs = node.get("outputs") or []
            output_names = [o.get("name", f"output_{i}") for i, o in enumerate(outputs)]
            result.append({
                "node_id": node["id"],
                "type": node.get("type", "Unknown"),
                "title": node.get("title", ""),
                "output_names": output_names,
            })
    return result


def _guess_label(node: dict, widget_idx: int) -> str:
    """Guess a human-readable label for a widget."""
    ntype = node.get("type", "")
    title = node.get("title", "")

    # Known node types with semantic widget ordering
    known = {
        "AWPTextInput": ["用户输入", "会话ID", "角色卡ID"],
        "AWPJsonInput": ["JSON数据"],
        "AWPPreset": ["预设ID"],
        "AWPMainAgent": ["用户输入", "会话ID"],
    }
    if ntype in known:
        labels = known[ntype]
        if widget_idx < len(labels):
            return labels[widget_idx]

    return f"{ntype} #{widget_idx + 1}"


def load_workflow(filename: str) -> dict | None:
    """Load a workflow JSON file."""
    path = WORKFLOW_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def convert_to_api_format(workflow: dict) -> dict:
    """Convert workflow save format to ComfyUI prompt API format.
    
    Handles widget_values (literal), links (node references), and resolves
    input slot names by dynamically importing node classes.
    """
    nodes = workflow.get("nodes", [])
    links = workflow.get("links", [])

    # Build link lookup: (to_node_id, to_slot) → (from_node_id, from_slot)
    link_map: dict[tuple[int, int], tuple[int, int]] = {}
    for link in links:
        from_node = link[1]; from_slot = link[2]
        to_node = link[3]; to_slot = link[4]
        link_map[(to_node, to_slot)] = (from_node, from_slot)

    prompt = {}
    for node in nodes:
        nid = str(node["id"])
        ntype = node["type"]
        node_inputs: dict[str, object] = {}
        raw_inputs = node.get("inputs") or []
        widgets = node.get("widgets_values") or []

        # Get required input names for this node type
        input_names = _get_node_input_names(ntype)

        if raw_inputs:
            # Node has explicit input slots in workflow
            for slot_idx, inp in enumerate(raw_inputs):
                inp_name = inp.get("name", f"slot_{slot_idx}")
                link_src = link_map.get((node["id"], slot_idx))
                if link_src is not None:
                    node_inputs[inp_name] = [str(link_src[0]), link_src[1]]
                elif slot_idx < len(widgets):
                    node_inputs[inp_name] = _coerce_widget(widgets[slot_idx])
        elif input_names and widgets:
            # Leaf node: map widgets to known input names
            for idx, name in enumerate(input_names):
                if idx < len(widgets):
                    node_inputs[name] = _coerce_widget(widgets[idx])
        elif widgets:
            # Fallback: unknown node type, use generic name
            node_inputs["text"] = _coerce_widget(widgets[0]) if widgets else ""

        prompt[nid] = {
            "inputs": node_inputs,
            "class_type": ntype,
        }

    return {"prompt": prompt}


def _coerce_widget(val: object) -> object:
    """Coerce widget values to ComfyUI API format."""
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
        return val  # Preserve JSON objects
    return val


# Cache for node input name lookups
_node_input_cache: dict[str, list[str]] = {}


def _get_node_input_names(node_type: str) -> list[str]:
    """Get the ordered list of required input names for a node type."""
    if node_type in _node_input_cache:
        return _node_input_cache[node_type]

    try:
        # Scan node registration for this type
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        cls = NODE_CLASS_MAPPINGS.get(node_type)
        if cls and hasattr(cls, "INPUT_TYPES"):
            input_types = cls.INPUT_TYPES()
            required = input_types.get("required", {})
            # Ordered names (Python 3.7+ dicts preserve insertion order)
            names = list(required.keys())
            _node_input_cache[node_type] = names
            return names
    except Exception:
        pass

    _node_input_cache[node_type] = []
    return []


def inject_inputs(workflow: dict, input_values: dict[str, list]) -> dict:
    """Inject user-provided values into workflow nodes.

    input_values: {node_id: [value_for_widget_0, value_for_widget_1, ...]}
    """
    nodes = workflow.get("nodes", [])
    for node in nodes:
        nid = str(node["id"])
        if nid in input_values:
            values = input_values[nid]
            widgets = node.get("widgets_values", [])
            for idx, val in enumerate(values):
                if idx < len(widgets):
                    # Preserve type if original was non-string
                    orig = widgets[idx] if idx < len(widgets) else ""
                    if isinstance(orig, bool):
                        widgets[idx] = val.lower() in ("true", "1", "yes")
                    elif isinstance(orig, (int, float)):
                        try:
                            widgets[idx] = type(orig)(val)
                        except (ValueError, TypeError):
                            widgets[idx] = val
                    else:
                        widgets[idx] = val
    return workflow


def call_comfyui(prompt: dict) -> dict:
    """Submit a prompt to ComfyUI and wait for results."""
    client_id = str(uuid.uuid4())[:8]
    payload = json.dumps({"prompt": prompt["prompt"], "client_id": client_id}).encode("utf-8")

    req = urllib.request.Request(
        f"{COMFYUI_URL}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
        if "error" in result:
            return {"ok": False, "error": result["error"]}

    prompt_id = result.get("prompt_id", "")
    if not prompt_id:
        return {"ok": False, "error": "No prompt_id returned"}

    # Poll for result
    for attempt in range(120):  # Max 120 seconds
        time.sleep(1)
        try:
            hist_req = urllib.request.Request(f"{COMFYUI_URL}/history/{prompt_id}")
            with urllib.request.urlopen(hist_req, timeout=10) as hresp:
                history = json.loads(hresp.read().decode())
        except Exception:
            continue

        if prompt_id in history:
            outputs = _extract_outputs(history[prompt_id])
            return {"ok": True, "prompt_id": prompt_id, "outputs": outputs}

    return {"ok": False, "error": "Timeout waiting for ComfyUI response"}


def _extract_outputs(history_entry: dict) -> dict[str, str]:
    """Extract text outputs from history entry."""
    outputs = {}
    for node_id, node_data in history_entry.get("outputs", {}).items():
        if isinstance(node_data, dict):
            for output_name, output_list in node_data.items():
                if isinstance(output_list, list) and output_list:
                    item = output_list[0]
                    if isinstance(item, dict) and "text" in item:
                        outputs[f"{node_id}/{output_name}"] = item["text"]
                    elif isinstance(item, str):
                        outputs[f"{node_id}/{output_name}"] = item
    return outputs


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent / "static"), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/workflows":
            self._json(list_workflows())
            return
        if parsed.path == "/api/health":
            self._json({"status": "ok", "comfyui": COMFYUI_URL})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        if parsed.path == "/api/run":
            self._handle_run(data)
        else:
            self._json({"error": "not found"}, 404)

    def _handle_run(self, data: dict):
        filename = data.get("workflow", "")
        input_values = data.get("inputs", {})

        wf = load_workflow(filename)
        if not wf:
            self._json({"ok": False, "error": f"Workflow not found: {filename}"})
            return

        try:
            wf = inject_inputs(wf, input_values)
            prompt = convert_to_api_format(wf)
            result = call_comfyui(prompt)
            self._json(result)
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


if __name__ == "__main__":
    print(f"\n  Workflow Runner Bridge")
    print(f"  Frontend: http://localhost:{PORT}")
    print(f"  ComfyUI:  {COMFYUI_URL}")
    print(f"  Ctrl+C to stop\n")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
