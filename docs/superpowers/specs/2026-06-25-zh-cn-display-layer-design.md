# zh-CN 显示层本地化设计

> 日期：2026-06-25
> 范围：ComfyUI 原生画布（节点标题/端口/widget/combo/核心菜单），仅改动本项目代码，不碰 ComfyUI 核心。

## 1. 背景与现状

ComfyUI 画布里 AWP RP 节点的标题、端口名、参数名、下拉枚举、菜单等对中文用户不友好。

现有汉化层 `comfyui_awp_rp/js/awp_widgets.js` 已部分覆盖，但存在两个问题：

1. **映射表手工维护，与 Python 节点定义脱钩** —— 节点新增/改字段后容易漏译。
2. **核心菜单未覆盖** —— ComfyUI 核心渲染的节点库搜索框、部分右键菜单项仍是英文。

经审查发现：
- `NODE_DISPLAY_NAME_MAPPINGS`、`RETURN_NAMES`、`CATEGORY` **已全部是中文**，节点标题、输出端口名、节点库分类天然显示中文，无需额外处理。
- 英文残留集中在：widget 标签（字段名）、combo 下拉显示值、input port label、ComfyUI 核心菜单项。

## 2. 目标

让 ComfyUI 原生画布的用户可见文本全面汉化，同时**绝对不改变内部协议**：

给用户看的 → 中文；给程序运行/保存/连线/API 调用用的 → 英文原样。

## 3. 方案

**方案 B：Python 反射生成权威映射表 + JS 拉取应用。**

用反射消除漏译，译文集中在 Python 一处维护，JS 层只做"取清单→应用显示层"的通用逻辑，不碰节点定义、不碰数据契约。

### 架构

```
Python 端（comfyui_awp_rp/）
  i18n/labels_zh.py        ← 单一中文译文字典（字段名→中文、combo值→中文、菜单项→中文）
  i18n/__init__.py         ← build_i18n_catalog(): 反射 NODE_CLASS_MAPPINGS + 合并译文字典 → dict
  __init__.py              ← 新增 /awp/i18n 端点，返回 build_i18n_catalog() 结果

JS 端（comfyui_awp_rp/js/）
  awp_widgets.js（重写）
    1. fetch('/awp/i18n') 缓存清单（widgetLabels / combos / portLabels / fallbackTable）
    2. registerExtension nodeCreated：翻译 widget.label、combo 显示值(回调反转回英文)、input.label
    3. 猴子补丁：尽力汉化节点库搜索/右键菜单/分类（失败则静默回退英文）
    4. 保留现有供应商设置面板逻辑
```

## 4. 反射提取逻辑

对 `NODE_CLASS_MAPPINGS` 中每个节点类 `cls`：

- 调 `cls.INPUT_TYPES()` → 遍历 `required` + `optional`
- 字段值是 `(list, opts)` 且 list 非空 → 记为 combo：`{key, 候选值列表}`
- 否则记为普通字段名 key
- `cls.RETURN_NAMES`、`cls.CATEGORY` 已中文，原样透传（输出端口天然汉化）

输出 catalog 结构：

```json
{
  "widgetLabels": { "user_input": "玩家输入", "session_id": "会话ID", ... },
  "combos": { "strategy": {"keyword":"关键词","bm25":"BM25",...}, ... },
  "portLabels": { "user_input": "玩家输入", ... },
  "menuLabels": { "Add Node": "添加节点", "Search": "搜索", ... }
}
```

`widgetLabels` / `portLabels` 字段名一致，但语义不同：widget 标签用于参数面板，port 标签用于输入端口。多数条目相同，分开维护以备差异。

## 5. 译文字典（`i18n/labels_zh.py`）

```python
WIDGET_LABELS = { "user_input": "玩家输入", "session_id": "会话ID", ... }
COMBO_VALUES  = { "strategy": {"keyword":"关键词","bm25":"BM25",...}, ... }
MENU_LABELS   = { "Add Node": "添加节点", "Search": "搜索", ... }
```

初始内容 = 现有 `awp_widgets.js` 的 `AWP_I18N_MAP` / `AWP_INPUT_PORT_MAP` / `AWP_COMBO_MAP` 平移过来，再补全反射发现但缺失的条目。`build_i18n_catalog()` 合并：反射出的字段名与字典取并集，字典有则用字典译文，无则保留英文 key（不报错）。

## 6. JS 应用逻辑（`awp_widgets.js`）

### 6.1 加载清单
启动时 `fetch('/awp/i18n')`，缓存到 `AWP_I18N`。fetch 失败时回退到文件内置的 `AWP_FALLBACK`（现有映射表的精简副本），保证离线/启动早期也有基本汉化。

### 6.2 nodeCreated 钩子（沿用现有成熟逻辑）
- widget 标签：`AWP_I18N.widgetLabels[widget.name]` → 赋值 `widget.label`（不动 `widget.name`）。
- combo：替换 `widget.options.values` 为中文显示值，重写 `widget.callback` 把中文反转回英文 key 写入 `widget.value`，**保存到 workflow 的仍是英文值**。
- input port：`AWP_I18N.portLabels[input.name]` → `input.label`（不动 `input.name` / handle id）。

### 6.3 核心菜单尽力汉化（脆弱层）
- 节点库分类、节点标题：天然中文，无需处理。
- 右键菜单英文项（"Add Node"/"Search"）、节点库搜索框 placeholder：猴子补丁，在 ComfyUI 渲染后扫描 DOM 文本节点替换为 `menuLabels`。包 try/catch + 版本探测，失败静默回退英文。

## 7. 数据契约红线（不可逾越）

以下保持英文原样，不翻译、不中文保存：

1. workflow JSON 字段 key
2. node type / schemaId / port id / React Flow handle id
3. 节点连接关系
4. API 请求参数名、后端 DTO 字段、数据库字段
5. **枚举真实保存值**（combo 中文显示 → 反转回英文写入 value）
6. provider/model 名等真实 ID 的**值** —— 输入框值保持 `deepseek`/`deepseek-chat` 原样显示与存储；仅字段标签汉化（"供应商"/"模型"）
7. card_id、tool_ids、skill_ids 等真实资源 ID
8. 已存在 workflow JSON 的内部英文结构、节点序列化格式

## 8. 错误处理

- `/awp/i18n` 端点用 `try/except` 包反射逻辑：单个节点反射失败不阻塞整体，返回部分清单 + 该节点跳过。
- JS fetch 失败 → 回退内置兜底表。
- JS 猴子补丁失败 → 静默回退英文显示。

## 9. 测试与验证

```bash
# 1. 反射覆盖全部节点
python -c "import sys; sys.path.insert(0, r'<项目根>'); from comfyui_awp_rp.i18n import build_i18n_catalog; c=build_i18n_catalog(); print('nodes widgets:', len(c['widgetLabels']), 'combos:', len(c['combos']))"

# 2. 节点注册回归（不破坏）
python -c "import sys; sys.path.insert(0, r'<项目根>'); from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS; print(len(NODE_CLASS_MAPPINGS))"

# 3. 现有回归测试
python comfyui_awp_rp/test_p6_p7_regressions.py
python comfyui_awp_rp/test_rp_pipeline_nodes.py
```

预期：39 节点全部注册，反射覆盖 39 节点的 INPUT_TYPES，combo 反转逻辑保证 workflow 保存英文值。

## 10. 不做（YAGNI）

- 不改 39 个节点的 `INPUT_TYPES` 源码（方案 C，风险高收益低）。
- 不动 ComfyUI 核心源码。
- 不汉化 React 故事工作台（`frontend/`）—— 那是另一个界面，本次范围外。
- 不汉化 server.py 错误文案 —— 本次范围外。
- 不引入 i18n 框架（i18next 等）—— 仅 zh-CN 单语言，字典够用。
