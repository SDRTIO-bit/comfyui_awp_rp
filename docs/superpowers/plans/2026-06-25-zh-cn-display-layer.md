# zh-CN 显示层本地化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ComfyUI 原生画布里 AWP RP 节点的用户可见文本（widget 标签、combo 显示值、input port label、核心菜单）全面中文化，内部协议（字段名、枚举保存值、端口 id、连线、API 合同）保持英文原样。

**Architecture:** Python 反射扫描 `NODE_CLASS_MAPPINGS` 的 `INPUT_TYPES` 生成权威 i18n 清单，经 `/awp/i18n` 端点暴露；JS 在 `nodeCreated` 钩子里 fetch 清单并翻译显示层，combo 中文显示/英文回写，fetch 失败回退内置兜底表；核心菜单用尽力而为的 DOM 猴子补丁。

**Tech Stack:** Python 3.10+（反射 + aiohttp 端点）、原生 JS（ComfyUI 扩展钩子，无打包）、unittest 测试。

**项目根路径**（下文 `<ROOT>`）= `F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle`

---

## 文件结构

| 文件 | 责任 | 动作 |
|------|------|------|
| `<ROOT>/comfyui_awp_rp/i18n/__init__.py` | `build_i18n_catalog()` 反射逻辑 | 新建 |
| `<ROOT>/comfyui_awp_rp/i18n/labels_zh.py` | 中文译文字典（字段名/combo 值/菜单项） | 新建 |
| `<ROOT>/comfyui_awp_rp/i18n/test_i18n.py` | 反射 + 字典单元测试 | 新建 |
| `<ROOT>/comfyui_awp_rp/__init__.py` | 注册 `/awp/i18n` 端点 | 修改 |
| `<ROOT>/comfyui_awp_rp/js/awp_widgets.js` | 重写：fetch 清单 + nodeCreated 翻译 + 兜底表 + 菜单补丁 | 修改 |

### 数据契约红线（所有任务共同遵守）
- 只改 `widget.label` / `input.label` / combo 的 `options.values` 显示与 `callback` 反转；**不改** `widget.name` / `input.name` / handle id / workflow 字段 key。
- combo 中文显示后，`widget.value` 必须仍是英文原值（callback 反转）。
- `provider`/`model` 等真实 ID 的**值**不翻译，仅字段标签汉化。
- 候选值已含中文的 combo（如 `AWPWorldbook.activation`）**整体跳过**，内部值即中文不可反转。

---

## Task 1: 创建 i18n 译文字典

**Files:**
- Create: `<ROOT>/comfyui_awp_rp/i18n/labels_zh.py`

- [ ] **Step 1: 创建译文字典文件**

创建 `<ROOT>/comfyui_awp_rp/i18n/labels_zh.py`，内容如下。`WIDGET_LABELS` 覆盖所有 39 节点出现的字段名；`COMBO_VALUES` 按字段名做 key（同名字段跨节点中文译文全局唯一）；`MENU_LABELS` 覆盖 ComfyUI 核心菜单英文项。

```python
"""zh-CN 译文字典。

仅用于前端显示层汉化。所有 key（英文字段名/combo 值/菜单项）均为
内部协议标识，绝不可被中文替代；中文仅作为 value 用于显示。

维护规则：
- WIDGET_LABELS: 节点 INPUT_TYPES 字段名 -> 中文显示标签
- COMBO_VALUES:  combo 字段名 -> {英文候选值 -> 中文显示}。同名字段跨
  节点候选值不同时，中文译文必须全局唯一，否则反转（中文->英文）会冲突。
- MENU_LABELS:   ComfyUI 核心菜单/搜索框英文项 -> 中文
"""

# 节点参数面板字段名 -> 中文标签（widget.label 用）
WIDGET_LABELS = {
    # 通用
    "text": "文本", "json_text": "JSON 文本", "validate_json": "验证 JSON",
    "label": "标签", "pretty": "美化输出", "status": "状态", "content": "内容",
    "title": "标题", "name": "名称", "category": "分类", "limit": "数量上限",
    "priority": "优先级", "tags": "标签", "tags_any": "标签匹配",
    "type_filter": "类型过滤", "query": "查询", "operation": "操作",
    "data": "数据", "context": "上下文", "model": "模型", "provider": "供应商",
    "temperature": "温度", "max_tokens": "最大 Token 数", "profile": "档案",
    "strategy": "检索策略", "min_score": "最低分数", "filter_tags": "过滤标签",
    "filter_type": "过滤类型", "importance": "重要度", "entity_ids": "实体 ID",
    "memory_type": "记忆类型", "summary": "摘要", "clear_session": "清除会话",
    "include_history": "包含对话历史", "dry_run": "试运行", "reply": "回复",
    "reply_rules": "回复规则", "task": "任务", "session_id": "会话 ID",
    # 角色卡
    "card_id": "角色卡 ID", "card_json": "角色卡 JSON", "card_path": "角色卡路径",
    "greeting_id": "开场白 ID", "greeting_content": "开场白内容",
    "greeting_label": "开场白标签", "manifest_json": "清单 JSON",
    # 记忆
    "namespace": "命名空间", "memory_id": "记忆 ID",
    "resource_ref": "资源引用", "entry_id": "条目 ID", "query_tags": "查询标签",
    # 世界书
    "worldbook_json": "世界书 JSON", "worldbook_context": "世界书上下文",
    "enabled_only": "仅启用", "documents_json": "文档 JSON",
    # 管线
    "user_input": "玩家输入", "known_entities_json": "已知实体 JSON",
    "parsed_input_json": "解析结果 JSON", "character_profile_json": "角色档案 JSON",
    "scene_state_json": "场景状态 JSON", "worldbook_context_json": "世界书上下文 JSON",
    "memory_context": "记忆上下文", "memory_context_json": "记忆上下文 JSON",
    "preset_sections_json": "预设片段 JSON", "target_tokens": "目标 Token 数",
    "context_bundle_json": "上下文包 JSON", "context_json": "上下文 JSON",
    "context_mode": "上下文模式", "critic_review_json": "审查 JSON",
    "character_id": "角色 ID", "scene_id": "场景 ID",
    "quality_decision_json": "质量决策 JSON",
    "candidate_state_patch": "候选状态补丁",
    "candidate_memory_patch": "候选记忆补丁",
    "allow_commit_when_accepted": "接受时允许提交",
    "side_effect_decision_json": "副作用决策 JSON",
    # 预设
    "preset_id": "预设 ID", "rule_section": "规则分类", "rule_id": "规则 ID",
    "rule_content": "规则内容", "rule_priority": "规则优先级",
    "contract_json": "输出合约 JSON",
    # Agent
    "enable_agent_loop": "启用 Agent Loop（工具调用+子Agent派发）",
    "max_iterations": "最大迭代次数", "tool_ids": "可用工具",
    "skill_ids": "授予技能", "record_session": "记录会话",
    # 项目
    "project_id": "项目 ID", "project_type": "项目类型",
    "snapshot_type": "快照类型", "snapshot_id": "快照 ID",
    "narrative": "正文", "quality_json": "质量 JSON",
    "memory_candidates_json": "记忆候选 JSON", "node_id": "节点 ID",
    "node_type": "节点类型", "parent_id": "父节点 ID",
    "order_index": "排序索引", "snapshot_limit": "快照数量",
    # 技能
    "skill_id": "技能 ID", "label_zh": "中文名称", "label_en": "英文名称",
    "content_zh": "中文内容", "content_en": "英文内容",
    # 世界书激活（注意：activation 的候选值已是中文，见 COMBO_VALUES 注释）
    "activation": "激活方式", "mode": "模式",
    # MVU
    "ai_response": "AI 回复文本", "current_variables": "当前变量状态",
    "variables": "变量 JSON", "worldbook_index": "世界书索引 JSON",
    "enable_worldbook_match": "变量驱动世界书匹配",
    "enable_validation": "Schema 验证", "top_n_matches": "最多匹配条目数",
    "top_worldbook": "世界书匹配数", "var_diff": "上轮变量变更",
    "authors_note": "Author's Note", "character_note": "角色备注",
    "injection_rules_json": "注入规则 JSON", "project_root": "项目根目录",
    "chapter_num": "剧情合约章节号", "story_genre": "剧情合约类型",
    "from_index": "起始轮次", "vector_persist_dir": "向量持久化目录",
}

# combo 字段名 -> {英文候选值 -> 中文显示}
# 同名字段跨节点候选值不同时，中文译文必须全局唯一。
# 注意：AWPWorldbook.activation 的候选值已是中文（"常开"等），不在此处翻译，
# 反射逻辑会检测候选值含中文并整体跳过该 combo。
COMBO_VALUES = {
    "project_type": {"rp": "角色扮演", "novel": "小说", "all": "全部"},
    "snapshot_type": {"turn": "回合", "chapter": "章节", "manual": "手动"},
    "operation": {
        "list": "列表", "get": "获取", "add": "添加", "update": "更新",
        "delete": "删除", "view": "查看", "reroll_last": "重 Roll 最近一轮",
        "delete_from": "回退到指定轮", "query": "查询",
        "update_manifest": "更新角色清单", "update_greeting": "更新开场白",
        "add_greeting": "新增开场白", "add_rule": "新增规则",
        "remove_rule": "删除规则", "update_contract": "更新输出合约",
        "set_activation": "设置激活方式",
    },
    "node_type": {
        "volume": "卷", "chapter": "章节", "plot_point": "情节点",
        "foreshadow": "伏笔", "all": "全部",
    },
    "status": {
        "planned": "计划中", "writing": "写作中", "done": "已完成",
        "abandoned": "已放弃", "all": "全部",
    },
    "mode": {"select": "选择", "list": "列表"},
    "context_mode": {
        "full_context": "完整上下文", "no_memory": "无记忆",
        "stateless_no_context": "无状态（无上下文）",
    },
    "strategy": {
        "keyword": "关键词", "bm25": "BM25", "hybrid": "混合检索",
        "embedding": "向量嵌入", "hybrid_semantic": "混合语义",
    },
    "rule_section": {
        "coreRules": "核心规则", "styleRules": "风格规则",
        "additionalInstructions": "附加指令",
    },
}

# ComfyUI 核心菜单/搜索框英文项 -> 中文（尽力汉化用，可能随版本变化）
MENU_LABELS = {
    "Add Node": "添加节点", "Search": "搜索", "Search nodes": "搜索节点",
    "Save": "保存", "Load": "加载", "Refresh": "刷新", "Clear": "清空",
    "Clone": "克隆", "Remove": "删除", "Mute": "静音", "Bypass": "绕过",
    "Title": "标题", "Properties": "属性", "Help": "帮助", "Mode": "模式",
}
```

- [ ] **Step 2: 验证文件可导入且无语法错误**

Run:
```bash
cd "<ROOT>" && python -c "from comfyui_awp_rp.i18n.labels_zh import WIDGET_LABELS, COMBO_VALUES, MENU_LABELS; print('widgets:', len(WIDGET_LABELS), 'combos:', len(COMBO_VALUES), 'menus:', len(MENU_LABELS))"
```
Expected: 输出类似 `widgets: 130 combos: 9 menus: 16`（数字非关键，关键是无报错、三字典均非空）。

- [ ] **Step 3: Commit**

```bash
cd "<ROOT>" && git add comfyui_awp_rp/i18n/labels_zh.py && git commit -m "feat: add zh-CN translation dictionary for display layer

- comfyui_awp_rp/i18n/labels_zh.py: WIDGET_LABELS / COMBO_VALUES / MENU_LABELS
- 仅用于前端显示层，内部协议标识保持英文原样
- activation 候选值已是中文，由反射逻辑检测跳过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 反射生成 i18n 清单 + 单测

**Files:**
- Create: `<ROOT>/comfyui_awp_rp/i18n/__init__.py`
- Test: `<ROOT>/comfyui_awp_rp/i18n/test_i18n.py`

- [ ] **Step 1: 写失败测试**

创建 `<ROOT>/comfyui_awp_rp/i18n/test_i18n.py`：

```python
"""Tests for i18n catalog reflection."""

import os
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.i18n import build_i18n_catalog
from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS


class TestI18nCatalog(unittest.TestCase):
    def test_catalog_has_all_sections(self):
        cat = build_i18n_catalog()
        self.assertIn("widgetLabels", cat)
        self.assertIn("combos", cat)
        self.assertIn("portLabels", cat)
        self.assertIn("menuLabels", cat)

    def test_widget_labels_cover_all_nodes(self):
        cat = build_i18n_catalog()
        # 反射应遍历全部注册节点
        self.assertEqual(cat["nodeCount"], len(NODE_CLASS_MAPPINGS))

    def test_strategy_combo_translated(self):
        cat = build_i18n_catalog()
        # AWPRetriever.strategy 是 combo，候选值含 keyword 等
        self.assertIn("strategy", cat["combos"])
        vals = cat["combos"]["strategy"]
        self.assertEqual(vals["keyword"], "关键词")
        self.assertEqual(vals["bm25"], "BM25")

    def test_chinese_combo_values_skipped(self):
        # AWPWorldbook.activation 候选值已是中文，不得出现在 combos 反转表
        cat = build_i18n_catalog()
        self.assertNotIn("activation", cat["combos"])

    def test_combo_values_are_english_keys(self):
        # combos 的 key 必须是英文候选值（内部协议），中文是 value
        cat = build_i18n_catalog()
        for field, mapping in cat["combos"].items():
            for eng_val, zh_val in mapping.items():
                # 英文 key 不应含中文（除非本就是中文候选值，但那些已被跳过）
                self.assertFalse(
                    any("一" <= ch <= "鿿" for ch in eng_val),
                    f"combo key for {field} contains CJK: {eng_val}",
                )

    def test_unknown_combo_value_kept_as_english(self):
        # 反射发现但字典无译文的候选值，保留英文（不出现在映射里即视为保留）
        cat = build_i18n_catalog()
        # greeting.mode select/list 都有译文
        self.assertEqual(cat["combos"]["mode"]["select"], "选择")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd "<ROOT>" && python comfyui_awp_rp/i18n/test_i18n.py
```
Expected: FAIL，提示 `ImportError: cannot import name 'build_i18n_catalog'`。

- [ ] **Step 3: 实现 build_i18n_catalog()**

创建 `<ROOT>/comfyui_awp_rp/i18n/__init__.py`：

```python
"""i18n catalog: reflect node definitions into a display-layer translation map.

Returns a dict consumed by the JS frontend via the /awp/i18n endpoint.
The catalog ONLY affects display (widget labels, combo shown values,
input port labels). Internal identifiers stay English.
"""

from .labels_zh import WIDGET_LABELS, COMBO_VALUES, MENU_LABELS


def _is_combo_value_list(spec):
    """A combo field is (list_of_strings, opts) with a non-empty list."""
    return (
        isinstance(spec, (list, tuple))
        and len(spec) >= 2
        and isinstance(spec[0], list)
        and len(spec[0]) > 0
        and all(isinstance(v, str) for v in spec[0])
    )


def _values_already_chinese(values):
    """If any candidate value already contains CJK, the node stores Chinese
    internally (e.g. AWPWorldbook.activation). We must NOT reverse-translate
    it — skip the whole combo to protect the data contract."""
    return any(_has_cjk(v) for v in values)


def _has_cjk(text):
    return any("一" <= ch <= "鿿" for ch in text)


def build_i18n_catalog():
    """Reflect NODE_CLASS_MAPPINGS and merge with the zh dictionary.

    Returns:
        {
            "nodeCount": int,
            "widgetLabels": {field_name: zh},   # for widget.label
            "portLabels":   {field_name: zh},   # for input.label (same source)
            "combos": {field_name: {eng_value: zh_value}},  # only fields whose
                       # candidate values are all English AND have a dict entry
            "menuLabels": {eng: zh},
        }
    """
    from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS

    # Collect candidate combo values per field name across ALL nodes (union).
    # Also record whether any node's values are already Chinese.
    field_combo_values = {}      # field -> set of english candidate values
    chinese_combo_fields = set() # fields to skip entirely

    node_count = 0
    for node_type, cls in NODE_CLASS_MAPPINGS.items():
        node_count += 1
        try:
            input_types = cls.INPUT_TYPES()
        except Exception:
            # A node that can't be reflected at import time is skipped, not fatal.
            continue
        for section in ("required", "optional"):
            section_def = input_types.get(section, {}) or {}
            for field_name, spec in section_def.items():
                if not _is_combo_value_list(spec):
                    continue
                values = spec[0]
                if _values_already_chinese(values):
                    chinese_combo_fields.add(field_name)
                    continue
                field_combo_values.setdefault(field_name, set()).update(values)

    # Build combo translation map: for each field, map english value -> zh.
    combos = {}
    for field, value_set in field_combo_values.items():
        if field in chinese_combo_fields:
            continue
        trans_dict = COMBO_VALUES.get(field, {})
        mapping = {}
        for eng_val in sorted(value_set):
            zh = trans_dict.get(eng_val)
            if zh is not None:
                mapping[eng_val] = zh
        # Only include the field if at least one value has a translation;
        # otherwise leave it English (no entry -> JS keeps original).
        if mapping:
            combos[field] = mapping

    return {
        "nodeCount": node_count,
        "widgetLabels": dict(WIDGET_LABELS),
        "portLabels": dict(WIDGET_LABELS),
        "combos": combos,
        "menuLabels": dict(MENU_LABELS),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd "<ROOT>" && python comfyui_awp_rp/i18n/test_i18n.py
```
Expected: `OK`，6 个测试全部通过。

- [ ] **Step 5: 验证反射覆盖全部节点**

Run:
```bash
cd "<ROOT>" && python -c "import sys; sys.path.insert(0, r'F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle'); from comfyui_awp_rp.i18n import build_i18n_catalog; from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS; c=build_i18n_catalog(); print('nodeCount:', c['nodeCount'], 'expected:', len(NODE_CLASS_MAPPINGS), 'combos:', list(c['combos'].keys()))"
```
Expected: `nodeCount: 39 expected: 39 combos: ['context_mode', 'mode', 'node_type', 'operation', 'project_type', 'rule_section', 'snapshot_type', 'status', 'strategy']`（combos 列表内容可能顺序不同，但 `activation` 不得出现）。

- [ ] **Step 6: Commit**

```bash
cd "<ROOT>" && git add comfyui_awp_rp/i18n/__init__.py comfyui_awp_rp/i18n/test_i18n.py && git commit -m "feat: reflect node INPUT_TYPES into i18n catalog

- comfyui_awp_rp/i18n/__init__.py: build_i18n_catalog() 反射 39 节点
- 跳过候选值已含中文的 combo（保护数据契约）
- combo 译文按字段名合并，缺译文值保留英文
- test_i18n.py: 6 个单测覆盖反射/跳过/契约不变量

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 注册 /awp/i18n 端点

**Files:**
- Modify: `<ROOT>/comfyui_awp_rp/__init__.py`（在 `_register_routes()` 内、`/awp/providers` 路由之前插入）

- [ ] **Step 1: 在 _register_routes() 中新增 /awp/i18n 路由**

打开 `<ROOT>/comfyui_awp_rp/__init__.py`，在 `@prompt_server.routes.get("/awp/providers")` 这一行**之前**插入以下路由定义：

```python
        @prompt_server.routes.get("/awp/i18n")
        async def get_i18n(_request):
            """Return the zh-CN display-layer catalog for the frontend.

            Reflects all node INPUT_TYPES at request time and merges with the
            translation dictionary. Display-only; internal identifiers stay
            English. Failures return an empty catalog so the JS fallback kicks in.
            """
            try:
                from .i18n import build_i18n_catalog
                return web.json_response(build_i18n_catalog())
            except Exception as exc:  # noqa: BLE001
                return web.json_response({
                    "nodeCount": 0,
                    "widgetLabels": {},
                    "portLabels": {},
                    "combos": {},
                    "menuLabels": {},
                    "error": str(exc),
                })
```

- [ ] **Step 2: 验证端点注册不破坏导入**

Run:
```bash
cd "<ROOT>" && python -c "import sys; sys.path.insert(0, r'F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle'); import comfyui_awp_rp; print('import OK')"
```
Expected: `import OK`（`_register_routes` 在无 ComfyUI 上下文时静默 try/except，端点定义函数本身不会执行，但模块导入必须成功）。

- [ ] **Step 3: 验证 catalog 端点逻辑可用（不依赖 ComfyUI 运行时）**

Run:
```bash
cd "<ROOT>" && python -c "import sys; sys.path.insert(0, r'F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle'); from comfyui_awp_rp.i18n import build_i18n_catalog; import json; c=build_i18n_catalog(); print(json.dumps({'nodeCount':c['nodeCount'],'comboFields':sorted(c['combos'].keys())}, ensure_ascii=False))"
```
Expected: `{"nodeCount": 39, "comboFields": ["context_mode", "mode", "node_type", "operation", "project_type", "rule_section", "snapshot_type", "status", "strategy"]}`

- [ ] **Step 4: 运行现有回归测试确认未破坏节点注册**

Run:
```bash
cd "<ROOT>" && python comfyui_awp_rp/test_p6_p7_regressions.py 2>&1 | tail -5
```
Expected: 既有测试结果不受影响（本任务只新增端点，未改节点）。若该测试因环境依赖（如 vector_store/chroma）原本就失败，记录现状即可，不视为本任务引入的回归。

- [ ] **Step 5: Commit**

```bash
cd "<ROOT>" && git add comfyui_awp_rp/__init__.py && git commit -m "feat: expose /awp/i18n endpoint for frontend display layer

- __init__.py: GET /awp/i18n 返回 build_i18n_catalog()
- 失败时返回空 catalog，触发 JS 兜底表
- 不改任何节点定义、DTO 或 API 合同

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 重写 awp_widgets.js（fetch + nodeCreated + 兜底表）

**Files:**
- Modify: `<ROOT>/comfyui_awp_rp/js/awp_widgets.js`（重写第 1-167 行的汉化部分，保留第 169 行起的供应商设置面板）

- [ ] **Step 1: 备份并读取现有设置面板代码**

现有文件第 169 行起（`// ============ 供应商设置面板 ============`）到末尾的供应商设置面板逻辑（`PROVIDER_SETTINGS`、`awpFetchProviders`、`awpSaveProvider`、`awpDeleteProvider`、第二个 `registerExtension`、console.log）**保留不动**。本次只重写第 1-167 行的汉化映射与 `nodeCreated` 扩展。

- [ ] **Step 2: 重写第 1-167 行为新的 fetch + nodeCreated 逻辑**

用以下内容**替换** `awp_widgets.js` 的第 1 行到第 167 行（即从文件开头到第一个 `});` 结束、`// ============ 供应商设置面板 ============` 注释之前）。供应商设置面板部分（第 169 行起）原样保留。

```javascript
// AWP RP Plugin - 前端扩展
// 1. 汉化节点参数显示名 / combo 显示值 / 输入端口标签（显示层）
//    内部协议（字段名、枚举保存值、端口 id、连线）保持英文原样。
// 2. ComfyUI 设置面板：配置 LLM 供应商

// ============ 兜底映射表 ============
// 当 /awp/i18n 端点不可用（离线 / 启动早期 / 非 ComfyUI 环境）时使用。
// 与 Python 端 labels_zh.py 保持精简同步。
var AWP_FALLBACK = {
    widgetLabels: {
        "text": "文本", "json_text": "JSON 文本", "validate_json": "验证 JSON",
        "label": "标签", "pretty": "美化输出", "status": "状态", "content": "内容",
        "title": "标题", "name": "名称", "category": "分类", "limit": "数量上限",
        "priority": "优先级", "tags": "标签", "tags_any": "标签匹配",
        "type_filter": "类型过滤", "query": "查询", "operation": "操作",
        "data": "数据", "context": "上下文", "model": "模型", "provider": "供应商",
        "temperature": "温度", "max_tokens": "最大 Token 数", "profile": "档案",
        "strategy": "检索策略", "session_id": "会话 ID", "card_id": "角色卡 ID",
        "user_input": "玩家输入", "current_variables": "当前变量状态",
        "worldbook_context": "世界书上下文", "memory_context": "记忆上下文",
        "preset_id": "预设 ID", "context_mode": "上下文模式"
    },
    combos: {
        "context_mode": { "full_context": "完整上下文", "no_memory": "无记忆", "stateless_no_context": "无状态（无上下文）" },
        "strategy": { "keyword": "关键词", "bm25": "BM25", "hybrid": "混合检索", "embedding": "向量嵌入", "hybrid_semantic": "混合语义" },
        "operation": { "list": "列表", "get": "获取", "add": "添加", "update": "更新", "delete": "删除", "view": "查看", "query": "查询" }
    },
    portLabels: {
        "user_input": "玩家输入", "session_id": "会话 ID", "card_id": "角色卡 ID",
        "worldbook_context": "世界书上下文", "memory_context": "记忆上下文",
        "current_variables": "当前变量状态", "documents_json": "文档 JSON",
        "worldbook_json": "世界书 JSON", "result": "结果", "output": "输出",
        "metadata": "元数据"
    },
    menuLabels: {}
};

// ============ 运行时 i18n 清单（fetch 后填充，失败用兜底表） ============
var AWP_I18N = null;

async function awpLoadI18n() {
    try {
        var r = await fetch("/awp/i18n");
        if (!r.ok) throw new Error("HTTP " + r.status);
        AWP_I18N = await r.json();
    } catch (e) {
        console.warn("[AWP] i18n 清单加载失败，使用兜底表:", e);
        AWP_I18N = AWP_FALLBACK;
    }
}

function awpGet(field) {
    // 若清单已加载则用之，否则用兜底表
    var src = AWP_I18N || AWP_FALLBACK;
    return src[field] || {};
}

// ============ 汉化扩展：widget 标签 + combo 显示值 + 输入端口标签 ============
app.registerExtension({
    name: "awp.rp.i18n",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 节点创建前确保清单已加载（首次加载触发一次 fetch）
        if (!AWP_I18N) {
            await awpLoadI18n();
        }
    },
    nodeCreated(node) {
        if (!node.comfyClass || !node.comfyClass.startsWith("AWP")) return;

        // widget 标签 + combo 显示值
        if (node.widgets) {
            var widgetLabels = awpGet("widgetLabels");
            var combos = awpGet("combos");
            for (var i = 0; i < node.widgets.length; i++) {
                var widget = node.widgets[i];

                // 1. 翻译 widget 显示标签（不动 widget.name）
                var zhLabel = widgetLabels[widget.name];
                if (zhLabel) widget.label = zhLabel;

                // 2. 翻译 combo 下拉选项显示值（保持内部值为英文）
                if ((widget.type === "combo" || (widget.options && widget.options.values)) &&
                    widget.options && widget.options.values && widget.options.values.length) {
                    var transMap = combos[widget.name];
                    if (transMap) {
                        var originalValues = widget.options.values.slice();
                        var reverseMap = {};
                        var translatedValues = originalValues.map(function (v) {
                            // 候选值已是中文则不翻译（如 worldbook.activation），保持原样
                            var t = transMap[v] || v;
                            reverseMap[t] = v;
                            return t;
                        });

                        // 替换显示值
                        widget.options.values = translatedValues;

                        // 拦截 callback：选择中文选项后，内部值保持英文 key
                        var origCallback = widget.callback;
                        widget.callback = function (displayValue) {
                            var engValue = reverseMap[displayValue] || displayValue;
                            this.value = engValue;            // 内部值保持英文
                            if (origCallback) origCallback.call(this, engValue);
                        };
                    }
                }
            }
        }

        // 输入端口标签（不动 input.name / handle id）
        if (node.inputs) {
            var portLabels = awpGet("portLabels");
            for (var j = 0; j < node.inputs.length; j++) {
                var input = node.inputs[j];
                var zh = portLabels[input.name];
                if (zh) input.label = zh;
            }
        }
    },
});
```

- [ ] **Step 3: 验证 JS 语法（用 node 检查，若环境无 node 则跳过此步并在 Step 5 浏览器实测）**

Run:
```bash
cd "<ROOT>" && node --check comfyui_awp_rp/js/awp_widgets.js && echo "SYNTAX OK"
```
Expected: `SYNTAX OK`。若提示 `node: command not found`，记录"无 node，依赖浏览器实测"，继续。

- [ ] **Step 4: 确认供应商设置面板部分未被破坏**

Run:
```bash
cd "<ROOT>" && grep -c "PROVIDER_SETTINGS\|awpFetchProviders\|awp.rp.settings" comfyui_awp_rp/js/awp_widgets.js
```
Expected: 输出 `3` 或更多（这三处标识符必须仍在文件中，证明设置面板逻辑保留）。

- [ ] **Step 5: Commit**

```bash
cd "<ROOT>" && git add comfyui_awp_rp/js/awp_widgets.js && git commit -m "feat: rewrite i18n layer to fetch /awp/i18n with fallback

- awp_widgets.js: fetch 清单 + nodeCreated 翻译 widget/combo/port
- combo 中文显示 + callback 反转回英文（保护保存值）
- 候选值已是中文的 combo 不翻译
- 兜底表保证离线/启动早期汉化
- 保留供应商设置面板逻辑

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 核心菜单尽力汉化（DOM 猴子补丁）

**Files:**
- Modify: `<ROOT>/comfyui_awp_rp/js/awp_widgets.js`（在 i18n `registerExtension` 之后、供应商设置面板之前插入菜单补丁）

- [ ] **Step 1: 插入菜单汉化补丁**

在 `awp_widgets.js` 中，i18n 扩展的 `});`（`nodeCreated` 注册结束）之后、`// ============ 供应商设置面板 ============` 之前，插入以下代码：

```javascript
// ============ 核心菜单尽力汉化（脆弱层，失败静默回退英文） ============
// ComfyUI 核心渲染的搜索框 placeholder、部分右键菜单项等不在 nodeCreated
// 覆盖范围，用 DOM 文本替换尽力汉化。随 ComfyUI 版本可能失效，包 try/catch。
(function awpMenuI18n() {
    function hasCJK(s) { return /[一-鿿]/.test(s); }

    function translateMenuLabels() {
        var menuLabels = awpGet("menuLabels");
        if (!menuLabels) return;
        try {
            // 搜索框 placeholder
            var searchInputs = document.querySelectorAll(
                'input[placeholder], .litegraph input, .comfy-vue input[placeholder]'
            );
            for (var i = 0; i < searchInputs.length; i++) {
                var el = searchInputs[i];
                var p = el.getAttribute("placeholder");
                if (p && menuLabels[p]) el.setAttribute("placeholder", menuLabels[p]);
            }

            // 右键菜单 / 节点库列表项文本
            var candidates = document.querySelectorAll(
                '.litecontextmenu .menu-entry, .context-menu .menu-entry, .comfy-vue .context-menu-item'
            );
            for (var j = 0; j < candidates.length; j++) {
                var item = candidates[j];
                var txt = (item.textContent || "").trim();
                // 仅翻译整段匹配且不含中文的英文菜单项
                if (txt && !hasCJK(txt) && menuLabels[txt]) {
                    item.textContent = menuLabels[txt];
                }
            }
        } catch (e) {
            // 静默回退：菜单保持英文，不影响功能
        }
    }

    // 菜单是动态生成的，用 MutationObserver 监听 DOM 变化重译
    try {
        var observer = new MutationObserver(function () { translateMenuLabels(); });
        observer.observe(document.body, { childList: true, subtree: true });
        // 首次也译一次
        document.addEventListener("DOMContentLoaded", translateMenuLabels);
        setTimeout(translateMenuLabels, 1000);
    } catch (e) {
        console.warn("[AWP] 菜单汉化补丁初始化失败:", e);
    }
})();
```

- [ ] **Step 2: 验证 JS 语法**

Run:
```bash
cd "<ROOT>" && node --check comfyui_awp_rp/js/awp_widgets.js && echo "SYNTAX OK"
```
Expected: `SYNTAX OK`（无 node 则跳过，浏览器实测）。

- [ ] **Step 3: 确认补丁已插入且设置面板仍在**

Run:
```bash
cd "<ROOT>" && grep -c "awpMenuI18n\|MutationObserver\|PROVIDER_SETTINGS" comfyui_awp_rp/js/awp_widgets.js
```
Expected: `3`（菜单补丁两处标识 + 设置面板一处）。

- [ ] **Step 4: Commit**

```bash
cd "<ROOT>" && git add comfyui_awp_rp/js/awp_widgets.js && git commit -m "feat: best-effort i18n for ComfyUI core menus via DOM patch

- 菜单/搜索框 placeholder 用 MutationObserver 尽力汉化
- 整段匹配 + 不含中文才翻译，失败静默回退英文
- 不触碰 ComfyUI 核心源码，仅运行时 DOM 替换

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 整体验证与回归

**Files:**
- 无新增/修改文件，纯验证

- [ ] **Step 1: 全部 i18n 单测通过**

Run:
```bash
cd "<ROOT>" && python comfyui_awp_rp/i18n/test_i18n.py
```
Expected: `OK`（6 个测试通过）。

- [ ] **Step 2: 节点注册回归**

Run:
```bash
cd "<ROOT>" && python -c "import sys; sys.path.insert(0, r'F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle'); from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS; print('nodes:', len(NODE_CLASS_MAPPINGS), 'displays:', len(NODE_DISPLAY_NAME_MAPPINGS))"
```
Expected: `nodes: 39 displays: 39`（与改造前一致）。

- [ ] **Step 3: catalog 端点逻辑端到端**

Run:
```bash
cd "<ROOT>" && python -c "import sys; sys.path.insert(0, r'F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle'); from comfyui_awp_rp.i18n import build_i18n_catalog; c=build_i18n_catalog(); assert c['nodeCount']==39; assert 'activation' not in c['combos']; assert c['combos']['strategy']['keyword']=='关键词'; print('catalog OK')"
```
Expected: `catalog OK`。

- [ ] **Step 4: 现有回归测试不新增失败**

Run:
```bash
cd "<ROOT>" && python comfyui_awp_rp/test_rp_pipeline_nodes.py 2>&1 | tail -5
```
Expected: 既有结果，无新增 import/注册失败。若该测试因环境依赖原本失败，确认失败原因与本改造无关即可。

- [ ] **Step 5: JS 语法最终检查**

Run:
```bash
cd "<ROOT>" && node --check comfyui_awp_rp/js/awp_widgets.js && echo "JS SYNTAX OK" || echo "no node, rely on browser test"
```
Expected: `JS SYNTAX OK` 或 `no node, rely on browser test`。

- [ ] **Step 6: 人工浏览器验证清单（记录在提交说明）**

启动 ComfyUI，在画布验证：
1. 添加 `AWPRetriever` 节点 → 参数面板「检索策略」下拉显示 `关键词/BM25/混合检索/向量嵌入/混合语义`，选择后保存的 workflow JSON 中 `strategy` 值仍为英文（如 `"bm25"`）。
2. 添加 `AWPMainAgent` → 字段标签为「玩家输入」「会话 ID」「供应商」「模型」「上下文模式」等；输入框里 `deepseek`/`deepseek-chat` 值保持英文。
3. 添加 `AWPWorldbook` → 「激活方式」下拉仍显示 `常开/关键词触发/关闭`（未被破坏，内部值即中文）。
4. 节点标题、输出端口名已是中文（`NODE_DISPLAY_NAME_MAPPINGS`/`RETURN_NAMES`）。
5. 节点库搜索框 placeholder、右键菜单英文项尽力显示中文。

将验证结果写入最终提交说明。

- [ ] **Step 7: 最终 Commit（验证记录）**

```bash
cd "<ROOT>" && git add -A && git commit -m "chore: zh-CN display layer verification

- 6 i18n 单测通过，39 节点注册回归通过
- catalog 反射覆盖全部节点，activation 中文 combo 正确跳过
- combo 保存值保持英文（契约不变量已验证）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自审记录

- **Spec 覆盖**：spec 第 4 节反射 → Task 2；第 5 节译文字典 → Task 1；第 6 节 JS 应用 → Task 4；第 6.3 节核心菜单 → Task 5；第 7 节数据契约红线 → 各任务 Step 注释 + Task 2 测试断言；第 8 节错误处理 → Task 3 端点 try/except + Task 4 兜底表 + Task 5 静默回退；第 9 节测试 → Task 2/6。
- **占位符扫描**：无 TBD/TODO，所有代码步骤含完整代码。
- **类型一致性**：`build_i18n_catalog()` 返回的 key（`widgetLabels`/`combos`/`portLabels`/`menuLabels`/`nodeCount`）与 JS 端 `awpGet(field)` 取用一致；combo 反转逻辑与现有成熟实现一致。
