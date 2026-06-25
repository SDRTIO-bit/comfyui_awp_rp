# AWP RP — ComfyUI 节点包

一个 ComfyUI 自定义节点包，为 RP（角色扮演）和小说/长篇小说工作流提供节点。

## 结构

```
comfyui_awp_rp/     Python 节点包（RP 核心实现）
  nodes/            ComfyUI 节点定义
  core/             LLM 路由、配置、SQLite 存储
  memory/           短期/长期记忆
  retrieval/        BM25/关键词/混合检索
  knowledge/        动态世界书
  card/             SillyTavern V3 角色卡导入
  profile/          Agent 档案（writer/critic/director/curator）
  preset/           RP 预设系统
  rp_pipeline.py    RP 回合管线逻辑

workflows/          RP 工作流 JSON（ComfyUI 画布）
plugins/            RP 节点插件和技能定义
scripts/            运行/测试脚本
docs/               项目文档
```

## 安装

将本目录放入 ComfyUI 的 `custom_nodes/` 文件夹，配置 `.env`（参考 `.env.example`）中的 LLM provider API key。

## License

见 `LICENSE`（如有）。否则适用各源文件中的默认版权声明。
