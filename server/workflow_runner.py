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
HOST = os.environ.get("RUNNER_HOST", "127.0.0.1")
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "RUNNER_CORS_ORIGINS",
        f"http://127.0.0.1:{PORT},http://localhost:{PORT},http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
}


def list_workflows() -> list[dict]:
    """List available workflow files with metadata."""
    workflows = []
    for f in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            if _is_api_prompt_format(wf):
                prompt = _unwrap_api_prompt(wf)
                nodes = _api_prompt_nodes(prompt)
                links = _api_prompt_links(prompt)
                inputs = _discover_inputs_api(prompt)
                outputs = _discover_outputs_api(prompt)
            else:
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


def _discover_inputs_api(prompt: dict) -> list[dict]:
    """Find input nodes in API format: nodes with literal inputs (not references)."""
    result = []
    for node_id, node in prompt.items():
        ntype = node.get("class_type", "Unknown")
        inputs = node.get("inputs", {})
        
        # Check if all inputs are literal values (not references)
        has_references = False
        fields = []
        field_idx = 0
        
        for inp_name, inp_value in inputs.items():
            # References are lists like ["node_id", output_index]
            if isinstance(inp_value, list) and len(inp_value) == 2 and isinstance(inp_value[0], (str, int)):
                has_references = True
                continue
            
            # This is a literal value
            if isinstance(inp_value, bool):
                fields.append({"index": field_idx, "label": inp_name, "type": "bool", "default": inp_value})
            elif isinstance(inp_value, (int, float)):
                fields.append({"index": field_idx, "label": inp_name, "type": "number", "default": inp_value})
            elif isinstance(inp_value, str):
                fields.append({"index": field_idx, "label": inp_name, "type": "text", "default": inp_value})
            field_idx += 1
        
        # Only include if has literal inputs and no references
        if fields and not has_references:
            title = (node.get("_meta") or {}).get("title", "")
            result.append({
                "node_id": node_id,
                "type": ntype,
                "title": title,
                "fields": fields,
            })
    return result


def _discover_outputs_api(prompt: dict) -> list[dict]:
    """Find output nodes in API format: nodes that are not referenced by others."""
    # Build set of node IDs that are referenced
    referenced = set()
    for node_id, node in prompt.items():
        inputs = node.get("inputs", {})
        for inp_value in inputs.values():
            if isinstance(inp_value, list) and len(inp_value) == 2 and isinstance(inp_value[0], (str, int)):
                referenced.add(str(inp_value[0]))
    
    # Output nodes are those not referenced by others
    result = []
    for node_id, node in prompt.items():
        if node_id not in referenced:
            ntype = node.get("class_type", "Unknown")
            title = (node.get("_meta") or {}).get("title", "")
            # Guess output names from class type
            output_names = []
            if 'Output' in ntype or 'output' in ntype.lower():
                output_names = ['output']
            elif 'Session' in ntype and 'Save' in ntype:
                output_names = ['status']
            elif 'Project' in ntype and 'Save' in ntype:
                output_names = ['project_id', 'status']
            else:
                output_names = ['result']
            
            result.append({
                "node_id": node_id,
                "type": ntype,
                "title": title,
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
    path = _safe_workflow_path(filename)
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _safe_workflow_path(filename: str) -> Path | None:
    """Resolve a workflow filename without allowing traversal outside workflows."""
    if not filename or Path(filename).name != filename:
        return None
    if Path(filename).suffix.lower() != ".json":
        return None
    root = WORKFLOW_DIR.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _is_api_prompt_format(workflow: dict) -> bool:
    prompt = _unwrap_api_prompt(workflow)
    return bool(prompt) and all(
        isinstance(v, dict) and "class_type" in v and "inputs" in v
        for v in prompt.values()
    )


def _unwrap_api_prompt(workflow: dict) -> dict:
    if isinstance(workflow.get("prompt"), dict):
        return workflow["prompt"]
    if "nodes" not in workflow and isinstance(workflow, dict):
        return workflow
    return {}


def _api_prompt_nodes(prompt: dict) -> list[dict]:
    nodes = []
    for node_id, node in prompt.items():
        try:
            nid = int(node_id)
        except (TypeError, ValueError):
            nid = node_id
        nodes.append({
            "id": nid,
            "type": node.get("class_type", "Unknown"),
            "inputs": node.get("inputs", {}),
            "title": (node.get("_meta") or {}).get("title", ""),
        })
    return nodes


def _api_prompt_links(prompt: dict) -> list[list]:
    links = []
    for to_id, node in prompt.items():
        try:
            to_node = int(to_id)
        except (TypeError, ValueError):
            continue
        for slot_idx, value in enumerate((node.get("inputs") or {}).values()):
            if _is_link_value(value):
                try:
                    links.append([None, int(value[0]), int(value[1]), to_node, slot_idx, ""])
                except (TypeError, ValueError):
                    continue
    return links


def convert_to_api_format(workflow: dict) -> dict:
    """Convert workflow save format to ComfyUI prompt API format.
    
    Handles widget_values (literal), links (node references), and resolves
    input slot names by dynamically importing node classes.
    """
    if _is_api_prompt_format(workflow):
        return {"prompt": _unwrap_api_prompt(workflow)}

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
        node_inputs = _map_node_inputs(node, link_map)

        prompt[nid] = {
            "inputs": node_inputs,
            "class_type": ntype,
        }

    return {"prompt": prompt}


def _coerce_widget(val: object) -> object:
    """Coerce widget values to ComfyUI API format."""
    if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
        return val  # Preserve JSON objects
    return val


# Cache for node input name lookups
_node_input_cache: dict[str, list[str]] = {}
_node_input_spec_cache: dict[str, list[dict]] = {}


def _get_node_input_names(node_type: str) -> list[str]:
    """Get the ordered list of input names for a node type."""
    if node_type in _node_input_cache:
        return _node_input_cache[node_type]

    names = [spec["name"] for spec in _get_node_input_specs(node_type)]
    _node_input_cache[node_type] = names
    return names


def _get_node_input_specs(node_type: str) -> list[dict]:
    """Get ordered input metadata from a ComfyUI node class."""
    if node_type in _node_input_spec_cache:
        return _node_input_spec_cache[node_type]

    try:
        _ensure_import_path()
        from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS
        cls = NODE_CLASS_MAPPINGS.get(node_type)
        if cls and hasattr(cls, "INPUT_TYPES"):
            input_types = cls.INPUT_TYPES()
            specs = []
            for section in ("required", "optional"):
                for name, raw_spec in (input_types.get(section, {}) or {}).items():
                    value_type, meta = _parse_input_spec(raw_spec)
                    specs.append({
                        "name": name,
                        "section": section,
                        "value_type": value_type,
                        "meta": meta,
                        "force_input": bool(meta.get("forceInput")),
                        "default": meta.get("default"),
                    })
            _node_input_spec_cache[node_type] = specs
            return specs
    except Exception:
        pass

    _node_input_spec_cache[node_type] = []
    return []


def _parse_input_spec(raw_spec: object) -> tuple[object, dict]:
    if isinstance(raw_spec, tuple) and raw_spec:
        value_type = raw_spec[0]
        meta = raw_spec[1] if len(raw_spec) > 1 and isinstance(raw_spec[1], dict) else {}
        return value_type, meta
    return raw_spec, {}


def _map_node_inputs(node: dict, link_map: dict[tuple[int, int], tuple[int, int]]) -> dict[str, object]:
    node_id = node["id"]
    raw_inputs = node.get("inputs") or []
    widgets = node.get("widgets_values") or []
    specs = _get_node_input_specs(node.get("type", ""))

    linked_inputs: dict[str, object] = {}
    linked_raw_names: set[str] = set()
    raw_input_names: list[str] = []
    for slot_idx, inp in enumerate(raw_inputs):
        inp_name = inp.get("name", f"slot_{slot_idx}")
        raw_input_names.append(inp_name)
        link_src = link_map.get((node_id, slot_idx))
        if link_src is not None:
            linked_inputs[inp_name] = [str(link_src[0]), link_src[1]]
            linked_raw_names.add(inp_name)

    if not specs:
        return _map_unknown_node_inputs(raw_inputs, widgets, linked_inputs)

    spec_names = [spec["name"] for spec in specs]
    candidate_orders = [
        spec_names,
        [name for name in spec_names if name not in linked_raw_names],
        [spec["name"] for spec in specs if not spec["force_input"]],
    ]

    best_inputs: dict[str, object] | None = None
    best_score: int | None = None
    for order in candidate_orders:
        candidate = _build_input_candidate(specs, order, widgets, linked_inputs)
        score = _score_input_candidate(specs, candidate)
        if best_score is None or score > best_score:
            best_score = score
            best_inputs = candidate

    return best_inputs or dict(linked_inputs)


def _map_unknown_node_inputs(raw_inputs: list[dict], widgets: list, linked_inputs: dict[str, object]) -> dict[str, object]:
    node_inputs = dict(linked_inputs)
    if raw_inputs:
        for slot_idx, inp in enumerate(raw_inputs):
            inp_name = inp.get("name", f"slot_{slot_idx}")
            if inp_name not in node_inputs and slot_idx < len(widgets):
                node_inputs[inp_name] = _coerce_widget(widgets[slot_idx])
    elif widgets:
        node_inputs["text"] = _coerce_widget(widgets[0])
    return node_inputs


def _build_input_candidate(
    specs: list[dict],
    widget_order: list[str],
    widgets: list,
    linked_inputs: dict[str, object],
) -> dict[str, object]:
    candidate: dict[str, object] = {}
    for idx, name in enumerate(widget_order):
        if idx >= len(widgets):
            break
        candidate[name] = _coerce_widget(widgets[idx])

    candidate.update(linked_inputs)

    for spec in specs:
        name = spec["name"]
        if name not in candidate and (spec["section"] == "required" or spec["force_input"]):
            if spec["default"] is not None:
                candidate[name] = spec["default"]
    return candidate


def _score_input_candidate(specs: list[dict], candidate: dict[str, object]) -> int:
    score = 0
    for spec in specs:
        name = spec["name"]
        if name not in candidate:
            if spec["section"] == "required":
                score -= 100
            continue
        score += _score_input_value(spec, candidate[name])
    return score


def _score_input_value(spec: dict, value: object) -> int:
    if _is_link_value(value):
        return 8

    value_type = spec["value_type"]
    if isinstance(value_type, (list, tuple)):
        return 12 if value in value_type else -40
    if value_type == "BOOLEAN":
        return 8 if isinstance(value, bool) else -20
    if value_type == "INT":
        return 8 if isinstance(value, int) and not isinstance(value, bool) else -20
    if value_type == "FLOAT":
        return 8 if isinstance(value, (int, float)) and not isinstance(value, bool) else -20
    if value_type == "STRING":
        return 6 if isinstance(value, str) else 1
    return 1


def _is_link_value(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


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


def call_comfyui(prompt: dict, disable_cache: bool = False) -> dict:
    """Submit a prompt to ComfyUI and wait for results."""
    client_id = str(uuid.uuid4())[:8]
    payload_data = {"prompt": prompt["prompt"], "client_id": client_id}
    if disable_cache:
        payload_data["disable_cache"] = True
    payload = json.dumps(payload_data).encode("utf-8")

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
            history_entry = history[prompt_id]
            if not _history_completed(history_entry):
                continue
            error = _history_error(history_entry)
            if error:
                return {"ok": False, "prompt_id": prompt_id, "error": error}
            outputs = _extract_outputs(history_entry)
            return {"ok": True, "prompt_id": prompt_id, "outputs": outputs}

    return {"ok": False, "error": "Timeout waiting for ComfyUI response"}


def _history_completed(history_entry: dict) -> bool:
    status = history_entry.get("status") or {}
    if "completed" in status:
        return bool(status.get("completed"))
    return True


def _history_error(history_entry: dict) -> str | None:
    status = history_entry.get("status") or {}
    status_str = str(status.get("status_str") or status.get("status") or "").lower()
    if status_str not in {"error", "failed", "failure"}:
        return None

    for message in status.get("messages") or []:
        payload = None
        if isinstance(message, (list, tuple)) and len(message) > 1:
            payload = message[1]
        elif isinstance(message, dict):
            payload = message
        if isinstance(payload, dict):
            for key in ("exception_message", "error", "message"):
                if payload.get(key):
                    return str(payload[key])
    return "ComfyUI execution failed"


def _extract_outputs(history_entry: dict) -> dict[str, str]:
    """Extract text outputs from history entry."""
    outputs = {}
    for node_id, node_data in history_entry.get("outputs", {}).items():
        if isinstance(node_data, dict):
            # 处理 ComfyUI 的 ui 输出格式
            if "ui" in node_data:
                ui_data = node_data["ui"]
                if isinstance(ui_data, dict):
                    # 查找 text 字段
                    if "text" in ui_data:
                        text_list = ui_data["text"]
                        if isinstance(text_list, list) and text_list:
                            outputs[f"{node_id}/text"] = str(text_list[0])
            
            # 处理标准输出格式
            for output_name, output_list in node_data.items():
                if output_name == "ui":
                    continue
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


def scan_avatars_dir() -> list[dict]:
    """Scan data/avatars/ directory for character card files."""
    avatars_dir = Path(__file__).parent.parent / "data" / "avatars"
    if not avatars_dir.exists():
        avatars_dir.mkdir(parents=True, exist_ok=True)
        return []
    
    results = []
    for f in sorted(avatars_dir.iterdir()):
        if f.suffix.lower() in (".json", ".png"):
            stat = f.stat()
            results.append({
                "filename": f.name,
                "path": str(f),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
    return results


def import_card_from_file(filepath: str) -> dict:
    """Import a character card from file path."""
    _ensure_import_path()
    from comfyui_awp_rp.card.import_card import CardImporter, load_card_json_from_file
    
    try:
        card_data = load_card_json_from_file(filepath)
        importer = CardImporter()
        result = importer.import_card(card_data)
        return {
            "ok": True,
            "card_id": result.card_id,
            "name": result.manifest.name,
            "already_existed": result.already_existed,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def import_card_from_upload(filename: str, file_data: bytes) -> dict:
    """Import a character card from uploaded file data."""
    avatars_dir = Path(__file__).parent.parent / "data" / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    
    # Save file to avatars directory
    filepath = avatars_dir / filename
    filepath.write_bytes(file_data)
    
    # Import from saved file
    return import_card_from_file(str(filepath))


def update_card_greetings(card_id: str, greetings: list[dict]) -> dict:
    """Update greetings for a character card."""
    _ensure_import_path()
    from comfyui_awp_rp.core.store import get_store
    
    try:
        store = get_store()
        card = store.load_card(card_id)
        if not card:
            return {"ok": False, "error": "Card not found"}
        
        # Update greetings
        store.save_card(
            card_id=card_id,
            manifest=card["manifest"],
            greetings=greetings,
            worldbook=card["worldbook"],
            deferred=card.get("deferred_worldbook", []),
            report=card.get("import_report", {}),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_card_worldbook(card_id: str, worldbook: list[dict]) -> dict:
    """Update worldbook entries for a character card."""
    _ensure_import_path()
    from comfyui_awp_rp.core.store import get_store
    
    try:
        store = get_store()
        card = store.load_card(card_id)
        if not card:
            return {"ok": False, "error": "Card not found"}
        
        # Update worldbook
        store.save_card(
            card_id=card_id,
            manifest=card["manifest"],
            greetings=card["greetings"],
            worldbook=worldbook,
            deferred=card.get("deferred_worldbook", []),
            report=card.get("import_report", {}),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_card_greetings(card_id: str) -> list[dict]:
    """Get greetings for a card."""
    _ensure_import_path()
    from comfyui_awp_rp.card.import_card import CardImporter
    importer = CardImporter()
    card = importer.get_card(card_id)
    if not card:
        return []
    return card.get("greetings", [])


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


def get_session_history(session_id: str) -> dict:
    """Get session history with turns."""
    _ensure_import_path()
    from comfyui_awp_rp.memory.short_term import AgentSessionManager
    
    try:
        manager = AgentSessionManager()
        key = manager.create_key(
            tenant_id="default",
            workflow_instance_id="comfyui-rp",
            conversation_id=session_id,
            agent_node_id="main-agent",
        )
        
        # 获取会话上下文
        turns, summary, truncated = manager.get_prompt_context(key, protected_tokens=0)
        
        # 转换为前端需要的格式
        turn_list = []
        for turn in turns:
            turn_list.append({
                "index": turn.turn_index,
                "action": str(turn.input) if turn.input else "",
                "narrative": str(turn.assistant_output) if turn.assistant_output else "",
            })
        
        return {
            "turns": turn_list,
            "turn_count": len(turn_list),
            "summary": summary,
            "truncated": truncated,
        }
    except Exception as e:
        return {"turns": [], "turn_count": 0, "error": str(e)}


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

# 节点类型是否支持 Agent Loop
AGENT_LOOP_NODES = {"AWPMainAgent"}


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

    if _is_api_prompt_format(wf):
        prompt = _unwrap_api_prompt(wf)
        nodes = _api_prompt_nodes(prompt)
        links = _api_prompt_links(prompt)
    else:
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
            # 标记是否支持 Agent Loop
            if ntype in AGENT_LOOP_NODES:
                roles[-1]["supports_agent_loop"] = True
                roles[-1]["override_inputs"] = ["provider", "model", "profile", "temperature", "max_tokens", "context_mode", "preset_id", "enable_agent_loop", "max_iterations", "skill_ids"]
            elif ntype == "AWPDialogueDirector":
                roles[-1]["supports_agent_loop"] = False
                roles[-1]["override_inputs"] = ["provider", "model", "temperature", "max_tokens", "context_mode"]
            continue

        # For text input nodes, disambiguate by downstream
        if ntype in ("AWPTextInput",):
            title_role = _role_from_title(node.get("title", ""))
            if title_role:
                roles.append({
                    "role": title_role,
                    "label": {"session_id": "会话ID", "card_id": "角色卡ID", "user_input": "用户输入"}.get(title_role, title_role),
                    "node_id": nid,
                    "node_type": ntype,
                    "confidence": "high",
                    "input_type": "textarea" if title_role == "user_input" else "text",
                })
                if title_role == "session_id":
                    roles[-1]["options_from"] = "/api/sessions"
                elif title_role == "card_id":
                    roles[-1]["options_from"] = "/api/cards"
                continue

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


def _role_from_title(title: str) -> str | None:
    lower = title.lower()
    if "user input" in lower or "用户输入" in title or "玩家输入" in title:
        return "user_input"
    if "session" in lower or "会话" in title:
        return "session_id"
    if ("card id" in lower or "角色卡id" in lower or "角色卡ID" in title) and "json" not in lower and "JSON" not in title:
        return "card_id"
    return None


def _roles_to_injections(workflow: dict, roles: dict, analysis: dict) -> tuple[dict[str, list], dict[str, dict]]:
    """Convert role-based values to node injections.
    
    Returns: (widget_injections, api_overrides)
    widget_injections: {node_id: [value, ...]}  for leaf node widgets
    api_overrides: {node_id: {input_name: value}} for non-leaf node input overrides
    """
    role_map = {}
    for role in analysis.get("roles", []):
        role_map.setdefault(role["role"], role)
    widgets: dict[str, list] = {}
    overrides: dict[str, dict] = {}
    api_prompt = _is_api_prompt_format(workflow)

    for role_name, role_value in roles.items():
        info = role_map.get(role_name)
        if not info:
            continue
        nid = str(info["node_id"])

        if role_name == "generator" and isinstance(role_value, dict):
            overrides[nid] = role_value
        elif api_prompt:
            input_name = _role_input_name(info["node_type"], role_name)
            if input_name:
                overrides.setdefault(nid, {})[input_name] = str(role_value)
        elif role_name == "preset":
            widgets.setdefault(nid, [None])
            widgets[nid][0] = role_value
        else:
            widgets.setdefault(nid, [None])
            widgets[nid][0] = str(role_value)

    return widgets, overrides


def _role_input_name(node_type: str, role_name: str) -> str | None:
    if node_type == "AWPTextInput":
        return "text"
    if node_type == "AWPJsonInput":
        return "json_text"
    if node_type == "AWPPreset" or role_name == "preset":
        return "preset_id"
    if role_name in {"user_input", "session_id", "card_id"}:
        return role_name
    return None


def convert_to_api_format_with_overrides(workflow: dict, overrides: dict[str, dict]) -> dict:
    """Like convert_to_api_format but applies input overrides for non-leaf nodes."""
    prompt = convert_to_api_format(workflow)
    for nid, ov in overrides.items():
        if nid in prompt.get("prompt", {}):
            prompt["prompt"][nid]["inputs"].update(ov)
    return prompt


_run_counter = 0


def _inject_run_id(workflow: dict) -> None:
    """给 AWPMemoryRead 节点注入递增 run_id，避免 ComfyUI 缓存。"""
    global _run_counter
    _run_counter += 1
    for nid, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "AWPMemoryRead":
            node.setdefault("inputs", {})["run_id"] = _run_counter


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
        if path == "/api/avatars":
            return self._json(scan_avatars_dir())
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
        if path.startswith("/api/session/"):
            session_id = path.split("/api/session/")[-1]
            return self._json(get_session_history(session_id))
        if path.startswith("/api/cards/") and path.endswith("/greetings"):
            card_id = path.split("/api/cards/")[-1].replace("/greetings", "")
            return self._json(get_card_greetings(card_id))
        if path.startswith("/api/cards/") and path.endswith("/worldbook"):
            card_id = path.split("/api/cards/")[-1].replace("/worldbook", "")
            return self._json(get_card_worldbook(card_id))
        if path.startswith("/api/workflows/") and path.endswith("/analyze"):
            fname = path.split("/api/workflows/")[-1].replace("/analyze", "")
            result = analyze_workflow(fname)
            if result is None:
                return self._json({"error": "Workflow not found"}, 404)
            return self._json(result)

        if path == "/favicon.ico":
            self.path = "/favicon.svg"
            return super().do_GET()

        # Fallback: serve static files (SPA routing)
        # Check if the request looks like an API call (starts with /api/) or a static file request
        # For SPA routing, serve index.html for non-API, non-file requests
        if not path.startswith("/api/") and "." not in path.split("/")[-1]:
            # SPA route — serve index.html
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        # Handle file upload for card import
        if path == "/api/cards/import":
            return self._handle_card_import()
        
        # Handle JSON body requests
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        if path == "/api/run":
            self._handle_run(data)
        elif path == "/api/run-roles":
            self._handle_run_roles(data)
        elif path.startswith("/api/cards/") and path.endswith("/greetings"):
            card_id = path.split("/api/cards/")[-1].replace("/greetings", "")
            result = update_card_greetings(card_id, data.get("greetings", []))
            self._json(result)
        elif path.startswith("/api/cards/") and path.endswith("/worldbook"):
            card_id = path.split("/api/cards/")[-1].replace("/worldbook", "")
            result = update_card_worldbook(card_id, data.get("worldbook", []))
            self._json(result)
        else:
            self._json({"error": "not found"}, 404)

    def _handle_card_import(self):
        """Handle multipart file upload for card import."""
        content_type = self.headers.get("Content-Type", "")
        
        if "multipart/form-data" not in content_type:
            self._json({"ok": False, "error": "Expected multipart/form-data"})
            return
        
        # Parse boundary
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        
        if not boundary:
            self._json({"ok": False, "error": "No boundary in Content-Type"})
            return
        
        # Read multipart body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        
        # Parse multipart (simple implementation)
        boundary_bytes = boundary.encode()
        parts = body.split(b"--" + boundary_bytes)
        
        filename = None
        file_data = None
        
        for part in parts[1:]:  # Skip first empty part
            if b"\r\n\r\n" not in part:
                continue
            
            header_end = part.index(b"\r\n\r\n")
            headers_raw = part[:header_end].decode("utf-8", errors="replace")
            content = part[header_end + 4:]
            
            # Remove trailing boundary marker
            if content.endswith(b"\r\n"):
                content = content[:-2]
            
            # Extract filename from Content-Disposition
            if "filename=" in headers_raw:
                for line in headers_raw.split("\r\n"):
                    if "filename=" in line:
                        fname_start = line.index("filename=") + 9
                        filename = line[fname_start:].strip('"')
                        file_data = content
                        break
        
        if not filename or not file_data:
            self._json({"ok": False, "error": "No file found in upload"})
            return
        
        # Validate file type
        if not filename.lower().endswith((".json", ".png")):
            self._json({"ok": False, "error": "Only .json and .png files are supported"})
            return
        
        result = import_card_from_upload(filename, file_data)
        self._json(result)
    
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
            # 注入递增 run_id 到 AWPMemoryRead 节点，避免缓存
            _inject_run_id(wf)
            prompt = convert_to_api_format_with_overrides(wf, api_overrides)
            result = call_comfyui(prompt)
            self._json(result)
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _json(self, data, code: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
if __name__ == "__main__":
    print(f"\n  Workflow Runner Bridge")
    print(f"  Frontend: http://{HOST}:{PORT}")
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
    server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
