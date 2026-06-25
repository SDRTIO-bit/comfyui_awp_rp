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
        except Exception as e:
            print(f"[workflow_runner] Failed to load {f.name}: {e}", file=sys.stderr)
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
                        widgets[idx] = str(val).lower() in ("true", "1", "yes")
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


# ═══ Local data endpoints (read from SQLite/JSON, no ComfyUI dependency) ═══

def _ensure_import_path():
    """Ensure the project root is on sys.path for imports."""
    root = str(Path(__file__).parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


def list_cards() -> list[dict]:
    """List imported character cards."""
    _ensure_import_path()
    from comfyui_awp_rp.card.import_card import CardImporter
    importer = CardImporter()
    return importer.list_cards()


def get_card_worldbook(card_id: str) -> list[dict]:
    """Get worldbook entries for a card."""
    _ensure_import_path()
    from comfyui_awp_rp.card.import_card import CardImporter
    importer = CardImporter()
    card = importer.get_card(card_id)
    if not card:
        return []
    entries = card.get("worldbook", [])
    result = []
    for e in entries:
        meta = e.get("metadata") or {}
        activation = "off"
        if meta.get("constant"):
            activation = "const"
        elif meta.get("selective") or (meta.get("enabled") and not meta.get("constant")):
            activation = "select"
        if not meta.get("enabled", True):
            activation = "off"
        result.append({
            "id": e.get("id", ""),
            "title": e.get("title"),
            "content": e.get("content", ""),
            "tags": e.get("tags", []),
            "priority": e.get("priority", 0),
            "activation": activation,
            "enabled": meta.get("enabled", True),
        })
    return result


def list_sessions() -> list[dict]:
    """List all agent sessions."""
    _ensure_import_path()
    from comfyui_awp_rp.memory.short_term import AgentSessionManager
    manager = AgentSessionManager()
    sessions = manager._memory._store.list_sessions()  # type: ignore[attr-defined]
    result = []
    for s in sessions:
        result.append({
            "session_id": s.get("conversation_id", ""),
            "turn_count": s.get("turn_count", 0),
            "updated_at": s.get("updated_at", ""),
        })
    return result


def list_presets() -> list[dict]:
    """List available RP presets."""
    _ensure_import_path()
    from comfyui_awp_rp.preset.preset import PresetManager
    manager = PresetManager()
    return manager.list_presets()


def list_providers() -> dict:
    """List configured LLM providers."""
    _ensure_import_path()
    from comfyui_awp_rp.core.config import get_config
    config = get_config()
    result = {}
    for pid, pc in config.providers.items():
        result[pid] = {
            "provider_id": pc.provider_id,
            "base_url": pc.base_url,
            "default_model": pc.default_model,
            "has_key": bool(pc.api_key),
        }
    return result


# ═══ Workflow analysis ═══

ROLE_DOWNSTREAM = {
    "AWPSessionLoad": "session_id",
    "AWPCardSelect": "card_id",
    "AWPInputParser": "user_input",
    "AWPRetriever": "user_input",
    "AWPRoundPreparer": "user_input",
}

DIRECT_ROLES = {
    "AWPPreset": "preset",
    "AWPDialogueDirector": "generator",
    "AWPMainAgent": "generator",
    "AWPJsonInput": "json_input",
}


def _get_downstream_types(node_id: int, links: list) -> set[str]:
    """Get the set of node types that a node connects to downstream."""
    downstream_ids = set()
    for link in links:
        if link[1] == node_id:
            downstream_ids.add(link[3])
    return downstream_ids


def _get_node_by_id(nodes: list, nid: int) -> dict | None:
    for n in nodes:
        if n["id"] == nid:
            return n
    return None


def analyze_workflow(filename: str) -> dict | None:
    """Analyze a workflow and return role mappings."""
    wf = load_workflow(filename)
    if not wf:
        return None

    nodes = wf.get("nodes", [])
    links = wf.get("links", [])

    # Build node type lookup
    node_types: dict[int, str] = {n["id"]: n.get("type", "") for n in nodes}

    roles = []
    unmatched = []

    for node in nodes:
        nid = node["id"]
        ntype = node.get("type", "")

        # Direct role match
        if ntype in DIRECT_ROLES:
            roles.append({
                "role": DIRECT_ROLES[ntype],
                "label": {"preset": "生成预设", "generator": "生成引擎", "json_input": "场景状态"}.get(DIRECT_ROLES[ntype], ntype),
                "node_id": nid,
                "node_type": ntype,
                "confidence": "high",
                "input_type": "textarea" if ntype == "AWPJsonInput" else "select" if ntype == "AWPPreset" else "text",
            })
            if ntype == "AWPDialogueDirector" or ntype == "AWPMainAgent":
                roles[-1]["override_inputs"] = ["provider", "model", "temperature", "max_tokens", "context_mode"]
            continue

        # For text input nodes, disambiguate by downstream
        if ntype in ("AWPTextInput",):
            downstream_ids = _get_downstream_types(nid, links)
            role = None
            for d_id in downstream_ids:
                d_type = node_types.get(d_id, "")
                if d_type in ROLE_DOWNSTREAM:
                    role = ROLE_DOWNSTREAM[d_type]
                    break
            if role:
                roles.append({
                    "role": role,
                    "label": {"session_id": "会话ID", "card_id": "角色卡ID", "user_input": "用户输入"}.get(role, role),
                    "node_id": nid,
                    "node_type": ntype,
                    "confidence": "high",
                    "input_type": "textarea" if role == "user_input" else "text",
                })
                if role == "session_id":
                    roles[-1]["options_from"] = "/api/sessions"
                elif role == "card_id":
                    roles[-1]["options_from"] = "/api/cards"
            else:
                unmatched.append({"node_id": nid, "type": ntype, "reason": "下游无匹配角色"})
            continue

        # Nodes with inputs but no role matched — skip silently (internal pipeline)

    return {
        "filename": filename,
        "node_count": len(nodes),
        "roles": roles,
        "unmatched": unmatched,
    }


def _roles_to_injections(workflow: dict, roles: dict, analysis: dict) -> tuple[dict[str, list], dict[str, dict]]:
    """Convert role-based values to node injections.
    
    Returns: (widget_injections, api_overrides)
    widget_injections: {node_id: [value, ...]}  for leaf node widgets
    api_overrides: {node_id: {input_name: value}} for non-leaf node input overrides
    """
    role_map = {r["role"]: r for r in analysis.get("roles", [])}
    widgets: dict[str, list] = {}
    overrides: dict[str, dict] = {}

    for role_name, role_value in roles.items():
        info = role_map.get(role_name)
        if not info:
            continue
        nid = str(info["node_id"])

        if role_name == "generator" and isinstance(role_value, dict):
            overrides[nid] = role_value
        elif role_name == "preset":
            widgets.setdefault(nid, [None])
            widgets[nid][0] = role_value
        else:
            widgets.setdefault(nid, [None])
            widgets[nid][0] = str(role_value)

    return widgets, overrides


def convert_to_api_format_with_overrides(workflow: dict, overrides: dict[str, dict]) -> dict:
    """Like convert_to_api_format but applies input overrides for non-leaf nodes."""
    prompt = convert_to_api_format(workflow)
    for nid, ov in overrides.items():
        if nid in prompt.get("prompt", {}):
            prompt["prompt"][nid]["inputs"].update(ov)
    return prompt


# ═══ Handler ═══

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent / "static"), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Static API routes
        if path == "/api/workflows":
            return self._json(list_workflows())
        if path == "/api/health":
            return self._json({"status": "ok", "comfyui": COMFYUI_URL})
        if path == "/api/cards":
            return self._json(list_cards())
        if path == "/api/sessions":
            return self._json(list_sessions())
        if path == "/api/presets":
            return self._json(list_presets())
        if path == "/api/providers":
            return self._json(list_providers())

        # Parameterized routes
        if path.startswith("/api/worldbook/"):
            card_id = path.split("/api/worldbook/")[-1]
            return self._json(get_card_worldbook(card_id))
        if path.startswith("/api/workflows/") and path.endswith("/analyze"):
            fname = path.split("/api/workflows/")[-1].replace("/analyze", "")
            result = analyze_workflow(fname)
            if result is None:
                return self._json({"error": "Workflow not found"}, 404)
            return self._json(result)

        # Fallback: serve static files (SPA routing)
        # Check if the request looks like an API call (starts with /api/) or a static file request
        # For SPA routing, serve index.html for non-API, non-file requests
        if not path.startswith("/api/") and "." not in path.split("/")[-1]:
            # SPA route — serve index.html
            self.path = "/index.html"
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
        elif parsed.path == "/api/run-roles":
            self._handle_run_roles(data)
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

    def _handle_run_roles(self, data: dict):
        """Handle run with role-based inputs."""
        filename = data.get("workflow", "")
        roles = data.get("roles", {})

        wf = load_workflow(filename)
        if not wf:
            self._json({"ok": False, "error": f"Workflow not found: {filename}"})
            return

        analysis = analyze_workflow(filename)
        if not analysis:
            self._json({"ok": False, "error": "Workflow analysis failed"})
            return

        try:
            widget_injections, api_overrides = _roles_to_injections(wf, roles, analysis)
            wf = inject_inputs(wf, widget_injections)
            prompt = convert_to_api_format_with_overrides(wf, api_overrides)
            result = call_comfyui(prompt)
            self._json(result)
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _json(self, data, code: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
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

    # Pre-import all modules to avoid import deadlocks in threaded handler
    print(f"  Pre-loading modules...")
    _ensure_import_path()
    try:
        from comfyui_awp_rp.card.import_card import CardImporter
        from comfyui_awp_rp.memory.short_term import AgentSessionManager
        from comfyui_awp_rp.preset.preset import PresetManager
        from comfyui_awp_rp.core.config import get_config
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        CardImporter().list_cards()  # warm SQLite connection
        print(f"  Modules loaded OK")
    except Exception as e:
        print(f"  Module pre-load FAILED: {e}")
        print(f"  Some API endpoints may fail on first request")

    print(f"  Ctrl+C to stop\n")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
