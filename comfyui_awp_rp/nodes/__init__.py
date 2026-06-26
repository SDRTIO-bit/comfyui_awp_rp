"""ComfyUI nodes for AWP RP Plugin."""

from .main_agent import AWPMainAgent
from .sub_agent import AWPSubAgent
from .memory_nodes import AWPMemoryRead, AWPMemoryWrite
from .worldbook_node import AWPWorldbook, AWPWorldbookList
from .retriever_node import AWPRetriever
from .card_nodes import AWPCardImport, AWPCardSelect, AWPGreeting
from .preset_node import AWPPreset
from .session_node import AWPSessionLoad, AWPSessionSave, AWPSessionReroll
from .input_nodes import AWPJsonInput, AWPJsonOutput, AWPTextInput, AWPTextOutput
from .project_nodes import (
    AWPProjectSave,
    AWPProjectLoad,
    AWPProjectList,
    AWPOutlineEditor,
    AWPOutlineQuery,
)
from .ui_nodes import (
    AWPMemoryList,
    AWPMemoryEdit,
    AWPCardEditor,
    AWPPresetEditor,
    AWPSkillManagerNode,
    AWPToolList,
)
from .pipeline_nodes import (
    AWPContextAssembler,
    AWPDialogueDirector,
    AWPInputParser,
    AWPOutputRenderer,
    AWPPatchProposal,
    AWPQualityGate,
    AWPSideEffectDecision,
    AWPRoundPreparer,
)
from .mvu_node import AWPMVUNode, AWPMVUMacroResolver
from .router_nodes import AWPRoundRouter, AWPSubAgentOrchestrator

NODE_CLASS_MAPPINGS = {
    "AWPMainAgent": AWPMainAgent,
    "AWPSubAgent": AWPSubAgent,
    "AWPMemoryRead": AWPMemoryRead,
    "AWPMemoryWrite": AWPMemoryWrite,
    "AWPWorldbook": AWPWorldbook,
    "AWPWorldbookList": AWPWorldbookList,
    "AWPRetriever": AWPRetriever,
    "AWPCardImport": AWPCardImport,
    "AWPCardSelect": AWPCardSelect,
    "AWPGreeting": AWPGreeting,
    "AWPPreset": AWPPreset,
    "AWPSessionLoad": AWPSessionLoad,
    "AWPSessionSave": AWPSessionSave,
    "AWPSessionReroll": AWPSessionReroll,
    "AWPTextInput": AWPTextInput,
    "AWPJsonInput": AWPJsonInput,
    "AWPTextOutput": AWPTextOutput,
    "AWPJsonOutput": AWPJsonOutput,
    "AWPInputParser": AWPInputParser,
    "AWPContextAssembler": AWPContextAssembler,
    "AWPDialogueDirector": AWPDialogueDirector,
    "AWPQualityGate": AWPQualityGate,
    "AWPPatchProposal": AWPPatchProposal,
    "AWPSideEffectDecision": AWPSideEffectDecision,
    "AWPOutputRenderer": AWPOutputRenderer,
    "AWPRoundPreparer": AWPRoundPreparer,
    "AWPProjectSave": AWPProjectSave,
    "AWPProjectLoad": AWPProjectLoad,
    "AWPProjectList": AWPProjectList,
    "AWPOutlineEditor": AWPOutlineEditor,
    "AWPOutlineQuery": AWPOutlineQuery,
    "AWPMemoryList": AWPMemoryList,
    "AWPMemoryEdit": AWPMemoryEdit,
    "AWPCardEditor": AWPCardEditor,
    "AWPPresetEditor": AWPPresetEditor,
    "AWPSkillManagerNode": AWPSkillManagerNode,
    "AWPToolList": AWPToolList,
    "AWPMVUNode": AWPMVUNode,
    "AWPMVUMacroResolver": AWPMVUMacroResolver,
    "AWPRoundRouter": AWPRoundRouter,
    "AWPSubAgentOrchestrator": AWPSubAgentOrchestrator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AWPMainAgent": "主Agent",
    "AWPSubAgent": "子Agent",
    "AWPMemoryRead": "记忆读取",
    "AWPMemoryWrite": "记忆写入",
    "AWPMemoryList": "记忆列表",
    "AWPMemoryEdit": "记忆编辑",
    "AWPWorldbook": "世界书",
    "AWPWorldbookList": "世界书列表",
    "AWPRetriever": "检索器",
    "AWPCardImport": "导入角色卡",
    "AWPCardSelect": "选择角色卡",
    "AWPCardEditor": "角色卡编辑",
    "AWPGreeting": "开场白",
    "AWPPreset": "预设",
    "AWPPresetEditor": "预设编辑",
    "AWPSessionLoad": "加载会话",
    "AWPSessionSave": "保存会话",
    "AWPSessionReroll": "重roll/回退",
    "AWPTextInput": "文本输入",
    "AWPJsonInput": "JSON输入",
    "AWPTextOutput": "文本输出",
    "AWPJsonOutput": "JSON输出",
    "AWPInputParser": "输入解析",
    "AWPContextAssembler": "上下文组装",
    "AWPDialogueDirector": "对话导演",
    "AWPQualityGate": "质量门",
    "AWPPatchProposal": "候选补丁",
    "AWPSideEffectDecision": "副作用决策",
    "AWPOutputRenderer": "最终输出",
    "AWPRoundPreparer": "回合预处理",
    "AWPProjectSave": "保存项目快照",
    "AWPProjectLoad": "加载项目快照",
    "AWPProjectList": "项目列表",
    "AWPOutlineEditor": "大纲编辑",
    "AWPOutlineQuery": "大纲查询",
    "AWPSkillManagerNode": "技能管理",
    "AWPToolList": "工具列表",
    "AWPMVUNode": "MVU变量更新",
    "AWPMVUMacroResolver": "MVU宏解析",
    "AWPRoundRouter": "回合路由",
    "AWPSubAgentOrchestrator": "子Agent编排",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
