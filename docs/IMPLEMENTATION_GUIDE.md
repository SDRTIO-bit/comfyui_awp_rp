# 实现指引 — 代码模式参考

> 本文档提供 AWP 项目中新增功能的代码模式模板。新 AI 会话可以直接复制修改。

---

## 新增 ComfyUI 节点

### 模式模板

```python
"""节点说明文档字符串。"""
import json
from typing import Any

class AWPNewNode:
    """节点描述。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 必填输入：名称、默认值、placeholder、forceInput
                "text_input": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "输入说明...",
                    "forceInput": True,
                }),
                "session_id": ("STRING", {
                    "default": "default",
                    "forceInput": True,
                }),
            },
            "optional": {
                # 可选输入
                "temperature": ("FLOAT", {
                    "default": 0.8,
                    "min": 0.0, "max": 2.0, "step": 0.1,
                }),
                "enable_feature": ("BOOLEAN", {"default": False}),
                "choices": (["option_a", "option_b"], {"default": "option_a"}),
            },
        }

    # RETURN_TYPES 和 RETURN_NAMES 必须对齐
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("结果", "元数据", "调试")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/你的分类"  # 分类路径用 / 分隔
    # OUTPUT_NODE = True  # 如果是输出节点

    def execute(self, text_input: str, session_id: str, **kwargs):
        """节点执行逻辑。"""
        # 1. 解析输入
        # 2. 执行逻辑
        # 3. 返回元组（必须与 RETURN_TYPES 对齐）
        return (result_text, metadata_json, debug_json)
```

### 注册节点（3 步）

**Step 1**: 在 `nodes/__init__.py` 顶部导入：
```python
from .new_node_file import AWPNewNode
```

**Step 2**: 在 `NODE_CLASS_MAPPINGS` 中注册：
```python
"AWPNewNode": AWPNewNode,
```

**Step 3**: 在 `NODE_DISPLAY_NAME_MAPPINGS` 中注册显示名：
```python
"AWPNewNode": "新节点",
```

---

## 新增 Tool

### 模式模板

```python
"""工具说明。"""
import json
from typing import Any
from ..registry import ToolRegistry, ToolDefinition

def _my_tool(args: dict[str, Any]) -> str:
    """工具执行函数。接收 dict 参数，返回字符串结果。"""
    param1 = args.get("param1", "default")
    param2 = args.get("param2", 0)

    if not param1:
        return "Error: param1 is required"

    # 执行逻辑...
    result = {"status": "ok", "param1": param1}
    return json.dumps(result, ensure_ascii=False, indent=2)

def register_my_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition(
        name="my_tool",  # LLM 调用时使用的名称
        description="工具描述（英文）。LLM 根据此描述决定何时调用。",
        parameters={
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "参数说明。",
                },
                "param2": {
                    "type": "integer",
                    "description": "参数说明。",
                    "default": 0,
                },
            },
            "required": ["param1"],
        },
        execute_fn=_my_tool,
        required_permissions=["my_category:read"],  # 权限标签
        category="my_category",  # 工具分类
    ))
```

### 注册工具

在 `tools/builtin/__init__.py` 的 `register_builtin_tools()` 中添加：

```python
from .my_tools import register_my_tools

# 在函数末尾添加
register_my_tools(registry)
```

---

## 新增 Skill

### 模式模板

在 `tools/skill_manager.py` 的 `_load_builtin_skills()` 方法的 `builtin` 列表中添加：

```python
Skill(
    skill_id="my_skill_id",          # 唯一ID，用于 skill_ids 参数
    label_zh="中文显示名",
    label_en="English Display Name",
    content_zh=(                     # 中文内容（注入到 system prompt）
        "## 标题\n"
        "具体技能内容...\n\n"
        "- 要点1\n"
        "- 要点2\n"
    ),
    content_en=(
        "## Title\n"
        "Specific skill content...\n"
    ),
    category="writing",              # writing/roleplay/safety/knowledge
    tags=["tag1", "tag2"],           # 用于搜索和过滤
),
```

---

## 新增检索策略

### 在 `retriever_node.py` 中添加

**Step 1**: 更新策略选项
```python
"strategy": (["keyword", "bm25", "hybrid", "embedding", "hybrid_semantic", "your_new_strategy"],
             {"default": "bm25"}),
```

**Step 2**: 在 `execute()` 方法中添加处理分支（在 `if strategy in ("embedding", "hybrid_semantic"):` 块之后）

---

## 修改 Agent System Prompt

### 位置: `nodes/main_agent.py`

系统消息在 `execute()` 方法的 `# --- Build the full system message ---` 注释附近组装（约第 234 行）。

**结构**:
```python
system_parts = [
    system_prompt,       # profile.foundational_system_prompt
    preset_text,         # RP Preset 内容
    contract_text,       # Output Contract
    skills_content,      # Skill 注入（来自 skill_ids 参数）
    context_text,        # Worldbook + Memory + History
]

# Agent loop 路径自动注入额外 Skills:
if enable_agent_loop:
    agent_core_skills = skill_manager.resolve_skills_content(
        ["rp_thinking_flow", "hard_gates_full"], "zh"
    )
    full_system += agent_core_skills
```

**如果需要添加新的自动注入 Skill**，在 agent loop 的 `agent_core_skills` 行添加 skill_id。

---

## 验证命令

### 语法检查
```bash
python -c "import py_compile; py_compile.compile(r'<完整路径>', doraise=True); print('OK')"
```

### 导入测试
```bash
python -c "import sys; sys.path.insert(0, r'<项目根目录>'); from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS; print(len(NODE_CLASS_MAPPINGS))"
```

### 功能测试
写一个 `test_xxx.py` 到临时目录，导入模块并测试关键路径。参考项目中已有的 `test_rp_pipeline_nodes.py`。

### MVU 引擎自测
```bash
python mvu/engine.py
```

---

## 项目关键常量和配置

| 常量 | 位置 | 值 |
|------|------|-----|
| 项目根目录 | - | `F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle` |
| Python 包名 | - | `comfyui_awp_rp` |
| 数据目录 | `core/config.py` | `data/` |
| 默认 Provider | `core/config.py` | `deepseek` |
| 默认 Model | `main_agent.py` | `deepseek-chat` |
| Session namespace | `memory/short_term.py` | `tenant_id="default"` |
| Agent node ID | session_node.py | `agent_node_id="main-agent"` |
| 最大迭代 | `main_agent.py` | `max_iterations=5` |
| 自我反思重试 | `main_agent.py` | `max_reflections=2` |
| 质量门禁违例级别 | `rp_pipeline.py` | 新增检查为 "warning"（不阻塞），旧检查为 "error"（阻塞） |

---

## 文件依赖关系图

```
core/types.py          ← 所有模块的类型定义基础
core/config.py         ← Provider 配置
core/store.py          ← SQLite 持久化（memory/session/worldbook 共用）
core/llm_router.py     ← LLM API 调用

memory/short_term.py   ← 依赖 core/store.py + core/types.py
memory/long_term.py    ← 依赖 core/store.py + core/types.py

retrieval/tokenizer.py ← 独立（无依赖）
retrieval/bm25.py      ← 依赖 retrieval/tokenizer.py + core/types.py
retrieval/embedding.py ← 依赖 retrieval/tokenizer.py + core/types.py
retrieval/scorer.py    ← 依赖 retrieval/bm25.py

mvu/engine.py          ← 独立（纯计算，零外部依赖）
mvu/matcher.py         ← 独立
mvu/checker.py         ← 独立

tools/registry.py      ← 依赖 core/types.py
tools/tool_executor.py ← 依赖 tools/registry.py
tools/skill_manager.py ← 依赖 core/store.py + core/config.py
tools/builtin/*.py     ← 依赖 tools/registry.py + 各自的功能模块

nodes/main_agent.py    ← 依赖 core/ + memory/ + tools/ + profile/ + preset/ + mvu/
nodes/pipeline_nodes.py← 依赖 rp_pipeline.py + profile/ + preset/ + mvu/
nodes/mvu_node.py      ← 依赖 mvu/
nodes/*.py             ← 各自依赖对应的功能模块

rp_pipeline.py         ← 独立（纯计算）
```

**规则**：`nodes/` 下的文件禁止相互导入（每个节点独立），只能导入 `comfyui_awp_rp` 下的其他模块。
