"""Project and outline nodes for saving/loading RP/novel progress."""

import json
import uuid
from typing import Any

from ..core.store import get_store


class AWPProjectSave:
    """保存当前工作流结果为项目快照。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_id": ("STRING", {
                    "default": "",
                    "placeholder": "项目ID（留空自动生成）",
                    "forceInput": True,
                }),
                "name": ("STRING", {
                    "default": "",
                    "placeholder": "项目名称",
                }),
            },
            "optional": {
                "project_type": (["rp", "novel"], {"default": "rp"}),
                "snapshot_type": (["turn", "chapter", "manual"], {"default": "turn"}),
                "narrative": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "正文/回复内容...",
                    "forceInput": True,
                }),
                "context_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "forceInput": True,
                }),
                "quality_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "forceInput": True,
                }),
                "memory_candidates_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "forceInput": True,
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("快照ID", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/项目"
    OUTPUT_NODE = True

    def execute(
        self,
        project_id: str,
        name: str,
        project_type: str = "rp",
        snapshot_type: str = "turn",
        narrative: str = "",
        context_json: str = "{}",
        quality_json: str = "{}",
        memory_candidates_json: str = "[]",
    ):
        store = get_store()

        # Auto-generate project ID if empty
        if not project_id:
            project_id = f"proj_{uuid.uuid4().hex[:12]}"

        # Create or update project
        existing = store.get_project(project_id)
        if not existing:
            store.save_project(
                project_id=project_id,
                name=name if name else f"Project {project_id}",
                project_type=project_type,
            )

        # Generate snapshot ID
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"

        # Parse JSON inputs
        context = self._safe_json(context_json, {})
        quality = self._safe_json(quality_json, {})
        memory_candidates = self._safe_json(memory_candidates_json, [])

        store.save_snapshot(
            project_id=project_id,
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            narrative=narrative,
            context=context,
            quality=quality,
            memory_candidates=memory_candidates,
        )

        status = f"Saved snapshot {snapshot_id} to project {project_id}"
        return (snapshot_id, status)

    def _safe_json(self, text: str, default: Any) -> Any:
        try:
            return json.loads(text) if text.strip() else default
        except json.JSONDecodeError:
            return default


class AWPProjectLoad:
    """加载项目快照以恢复之前的进度。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_id": ("STRING", {
                    "default": "",
                    "placeholder": "项目ID",
                    "forceInput": True,
                }),
            },
            "optional": {
                "snapshot_id": ("STRING", {
                    "default": "",
                    "placeholder": "快照ID（留空=加载最新）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("正文", "上下文JSON", "质量JSON", "记忆候选JSON", "项目信息")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/项目"

    def execute(self, project_id: str, snapshot_id: str = ""):
        store = get_store()

        # Get project info
        project = store.get_project(project_id)
        if not project:
            empty = json.dumps({}, ensure_ascii=False)
            return ("", empty, empty, "[]", json.dumps({"error": "Project not found"}, ensure_ascii=False))

        project_info = json.dumps(project, ensure_ascii=False, indent=2)

        # Get snapshot
        if snapshot_id:
            snapshot = store.get_snapshot(project_id, snapshot_id)
        else:
            # Get latest snapshot
            snapshots = store.list_snapshots(project_id, limit=1)
            snapshot = snapshots[0] if snapshots else None

        if not snapshot:
            empty = json.dumps({}, ensure_ascii=False)
            return ("", empty, empty, "[]", project_info)

        narrative = snapshot.get("narrative", "")
        context_json = json.dumps(snapshot.get("context", {}), ensure_ascii=False, indent=2)
        quality_json = json.dumps(snapshot.get("quality", {}), ensure_ascii=False, indent=2)
        memory_candidates_json = json.dumps(snapshot.get("memory_candidates", []), ensure_ascii=False, indent=2)

        return (narrative, context_json, quality_json, memory_candidates_json, project_info)


class AWPProjectList:
    """列出所有项目及其最近的快照。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "project_type": (["all", "rp", "novel"], {"default": "all"}),
                "snapshot_limit": ("INT", {"default": 3, "min": 0, "max": 20}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("项目列表文本", "项目列表JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/项目"
    OUTPUT_NODE = True

    def execute(self, project_type: str = "all", snapshot_limit: int = 3):
        store = get_store()
        projects = store.list_projects()

        if project_type != "all":
            projects = [p for p in projects if p["type"] == project_type]

        result: list[dict[str, Any]] = []
        lines: list[str] = []
        for p in projects:
            snapshots = store.list_snapshots(p["project_id"], limit=snapshot_limit)
            entry = {
                "project_id": p["project_id"],
                "name": p["name"],
                "type": p["type"],
                "updated_at": p["updated_at"],
                "snapshot_count": len(snapshots),
                "recent_snapshots": [
                    {
                        "id": s["id"],
                        "type": s["snapshot_type"],
                        "created_at": s["created_at"],
                        "narrative_preview": (s.get("narrative") or "")[:100],
                    }
                    for s in snapshots
                ],
            }
            result.append(entry)
            lines.append(f"[{p['type']}] {p['name']} ({p['project_id']})")
            lines.append(f"  更新: {p['updated_at']}, 快照: {len(snapshots)}")
            for s in snapshots:
                preview = (s.get("narrative") or "")[:60]
                lines.append(f"  - {s['id']} ({s['snapshot_type']}): {preview}")
            lines.append("")

        text = "\n".join(lines) if lines else "(No projects found)"
        return (text, json.dumps(result, ensure_ascii=False, indent=2))


class AWPOutlineEditor:
    """查看、添加、更新或删除大纲节点（卷、章节、情节点）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_id": ("STRING", {
                    "default": "",
                    "placeholder": "项目ID",
                    "forceInput": True,
                }),
                "operation": (["list", "get", "add", "update", "delete"], {"default": "list"}),
            },
            "optional": {
                "node_id": ("STRING", {"default": "", "placeholder": "节点ID（get/update/delete时需要）"}),
                "node_type": (["volume", "chapter", "plot_point", "foreshadow"], {"default": "chapter"}),
                "title": ("STRING", {"default": "", "placeholder": "标题"}),
                "content": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "内容/摘要...",
                }),
                "parent_id": ("STRING", {"default": "", "placeholder": "父节点ID"}),
                "order_index": ("INT", {"default": 0, "min": 0, "max": 9999}),
                "status": (["planned", "writing", "done", "abandoned"], {"default": "planned"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("结果文本", "结果JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/项目"
    OUTPUT_NODE = True

    def execute(
        self,
        project_id: str,
        operation: str,
        node_id: str = "",
        node_type: str = "chapter",
        title: str = "",
        content: str = "",
        parent_id: str = "",
        order_index: int = 0,
        status: str = "planned",
    ):
        store = get_store()

        if operation == "list":
            nodes = store.list_outline_nodes(project_id)
            return self._format_list(nodes)

        elif operation == "get":
            if not node_id:
                return ("Error: node_id required for get", "{}")
            node = store.get_outline_node(project_id, node_id)
            if node:
                return (json.dumps(node, ensure_ascii=False, indent=2), json.dumps(node, ensure_ascii=False))
            return ("Node not found", "{}")

        elif operation == "add":
            if not title and not content:
                return ("Error: title or content required for add", "{}")
            nid = node_id or f"node_{uuid.uuid4().hex[:8]}"
            store.save_outline_node(
                project_id=project_id,
                node_id=nid,
                node_type=node_type,
                title=title,
                content=content,
                parent_id=parent_id,
                order_index=order_index,
                status=status,
            )
            return (f"Added: {nid}", json.dumps({"node_id": nid}, ensure_ascii=False))

        elif operation == "update":
            if not node_id:
                return ("Error: node_id required for update", "{}")
            existing = store.get_outline_node(project_id, node_id)
            if not existing:
                return ("Node not found", "{}")
            store.save_outline_node(
                project_id=project_id,
                node_id=node_id,
                node_type=node_type if node_type != "chapter" else existing["node_type"],
                title=title if title else existing["title"],
                content=content if content else existing["content"],
                parent_id=parent_id if parent_id else existing["parent_id"],
                order_index=order_index if order_index else existing["order_index"],
                status=status if status != "planned" else existing["status"],
            )
            return (f"Updated: {node_id}", json.dumps({"node_id": node_id}, ensure_ascii=False))

        elif operation == "delete":
            if not node_id:
                return ("Error: node_id required for delete", "{}")
            success = store.delete_outline_node(project_id, node_id)
            return (f"Deleted: {success}", "{}")

        return ("Unknown operation", "{}")

    def _format_list(self, nodes: list[dict[str, Any]]) -> tuple[str, str]:
        if not nodes:
            return ("(No outline nodes)", "[]")
        lines: list[str] = []
        for n in nodes:
            status_icon = {"planned": "○", "writing": "◐", "done": "●", "abandoned": "✕"}.get(n["status"], "?")
            lines.append(f"{status_icon} [{n['node_type']}] {n['title'] or n['node_id']} (order={n['order_index']})")
            if n["content"]:
                lines.append(f"  {n['content'][:120]}")
        return ("\n".join(lines), json.dumps(nodes, ensure_ascii=False, indent=2))


class AWPOutlineQuery:
    """按类型、状态或父节点查询大纲节点（只读）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_id": ("STRING", {
                    "default": "",
                    "placeholder": "项目ID",
                    "forceInput": True,
                }),
            },
            "optional": {
                "node_type": (["all", "volume", "chapter", "plot_point", "foreshadow"], {"default": "all"}),
                "status": (["all", "planned", "writing", "done", "abandoned"], {"default": "all"}),
                "parent_id": ("STRING", {"default": "", "placeholder": "父节点ID（留空=全部）"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("大纲文本", "大纲JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/项目"
    OUTPUT_NODE = True

    def execute(
        self,
        project_id: str,
        node_type: str = "all",
        status: str = "all",
        parent_id: str = "",
    ):
        store = get_store()
        nodes = store.list_outline_nodes(
            project_id,
            parent_id=parent_id if parent_id else None,
            node_type=node_type if node_type != "all" else None,
        )

        if status != "all":
            nodes = [n for n in nodes if n["status"] == status]

        if not nodes:
            return ("(No matching outline nodes)", "[]")

        lines: list[str] = []
        for n in nodes:
            lines.append(f"[{n['node_type']}/{n['status']}] {n['title'] or n['node_id']}")
            if n["content"]:
                lines.append(f"  {n['content'][:200]}")
        return ("\n".join(lines), json.dumps(nodes, ensure_ascii=False, indent=2))
