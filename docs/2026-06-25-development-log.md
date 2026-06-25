# 2026-06-25 开发日志

## 今日完成的工作

### 一、角色卡管理系统优化

#### 1.1 AWPCardImport 节点改进
- **问题**：之前删除了 `card_json` 参数，导致旧工作流报错
- **解决**：恢复 `card_json` 参数为可选，支持两种导入方式
  - 文件路径（推荐）：填写 .json 或 .png 文件路径
  - JSON 文本（兼容旧工作流）：直接粘贴角色卡 JSON

#### 1.2 Web 端角色卡导入功能
- **新增功能**：前端"导入角色卡"按钮
- **实现方式**：文件上传 → 保存到 `data/avatars/` → 自动导入
- **API 端点**：`POST /api/cards/import`

#### 1.3 角色卡编辑功能
- **新增组件**：`CardEditor.tsx`
- **支持功能**：
  - 编辑开场白（修改内容）
  - 编辑世界书条目（修改标题、内容、优先级、激活方式）
- **API 端点**：
  - `GET/POST /api/cards/{id}/greetings`
  - `GET/POST /api/cards/{id}/worldbook`

### 二、Web 端功能增强

#### 2.1 历史对话加载
- **问题**：选择会话后看不到过去的对话内容
- **解决**：添加 `loadSessionHistory` 函数，选择会话时自动加载历史
- **API 端点**：`GET /api/session/{id}`

#### 2.2 世界书显示优化
- **问题**：内容被 `line-clamp-2` 限制，无法查看完整内容
- **解决**：添加展开/收起功能，点击可查看完整内容

### 三、工作流兼容性修复

#### 3.1 支持 API 格式工作流
- **问题**：只有 `rp_full_node_workflow.json` 显示输入/输出，其他都是 0
- **原因**：代码只支持 ComfyUI 节点格式，不支持 API 格式
- **解决**：添加 `_discover_inputs_api` 和 `_discover_outputs_api` 函数

#### 3.2 创建 Agent Loop 工作流
- **新增文件**：`workflows/rp_agent_web_v1.json`
- **特点**：使用 `AWPMainAgent`，支持 Agent Loop
- **节点组成**：
  - RoundPreparer → MainAgent → MVUNode → QualityGate → OutputRenderer

#### 3.3 修复 ComfyUI 输出解析
- **问题**：`_extract_outputs` 函数没有正确解析 ComfyUI 的 `ui` 输出格式
- **解决**：更新解析逻辑，支持 `{"ui": {"text": [...]}}` 格式

### 四、后端 API 新增

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/avatars` | GET | 扫描 `data/avatars/` 目录 |
| `/api/cards/import` | POST | 上传并导入角色卡 |
| `/api/session/{id}` | GET | 获取会话历史对话 |
| `/api/cards/{id}/greetings` | GET/POST | 获取/保存开场白 |
| `/api/cards/{id}/worldbook` | GET/POST | 获取/保存世界书 |

### 五、文件变更清单

#### 修改的文件
- `comfyui_awp_rp/nodes/card_nodes.py` - 恢复 card_json 参数
- `comfyui_awp_rp/preset/__init__.py` - 预设模块初始化
- `comfyui_awp_rp/preset/preset.py` - 预设管理
- `frontend/src/components/ResourcePanel.tsx` - 资源面板组件
- `frontend/src/pages/RPPage.tsx` - 主页面逻辑
- `frontend/src/types.ts` - TypeScript 类型定义
- `server/server.py` - 本地服务器
- `server/static/index.html` - 前端入口
- `server/workflow_runner.py` - 工作流运行器

#### 新增的文件
- `frontend/src/components/CardEditor.tsx` - 角色卡编辑组件
- `workflows/rp_agent_web_v1.json` - Agent Loop 工作流

---

## 待办事项

### 高优先级
- [ ] 测试所有工作流是否能正常运行
- [ ] 测试角色卡导入功能
- [ ] 测试历史对话加载功能

### 中优先级
- [ ] 优化前端 UI 样式
- [ ] 添加角色卡删除功能
- [ ] 添加世界书条目添加/删除功能

### 低优先级
- [ ] 添加工作流模板管理
- [ ] 添加批量导入角色卡功能
- [ ] 优化错误提示信息

---

## 技术细节

### 工作流格式说明

#### 节点格式（ComfyUI 原生）
```json
{
  "nodes": [...],
  "links": [...]
}
```

#### API 格式（直接执行）
```json
{
  "1": {
    "class_type": "AWPTextInput",
    "inputs": {"text": "..."}
  }
}
```

### 角色卡存储结构
```
data/
├── avatars/          # 原始角色卡文件（备份）
└── awp.db           # SQLite 数据库
    └── character_cards 表
        ├── card_id
        ├── manifest_json
        ├── greetings_json
        ├── worldbook_json
        └── import_report_json
```

---

## 问题记录

### 已解决
1. ✅ AWPCardImport 参数兼容性问题
2. ✅ API 格式工作流输入/输出发现
3. ✅ 前端世界书显示限制
4. ✅ 历史对话加载缺失
5. ✅ ComfyUI 输出解析格式

### 待解决
1. ⏳ 网络连接问题导致 git push 失败
2. ⏳ 部分工作流可能还有兼容性问题

---

## 总结

今日主要完成了角色卡管理系统的优化和 Web 端功能增强。核心改进包括：

1. **角色卡导入**：支持文件路径和 JSON 文本两种方式，向后兼容旧工作流
2. **角色卡编辑**：新增开场白和世界书编辑功能
3. **工作流兼容**：支持 API 格式工作流，创建 Agent Loop 工作流
4. **用户体验**：修复历史对话加载、世界书显示等问题

下一步需要进行完整测试，确保所有功能正常工作。
