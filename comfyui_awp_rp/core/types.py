"""
Core type definitions for AWP RP Plugin.

Mirrors the TypeScript types from workflow-core, agent-runtime, and plugin-sdk.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Union
from enum import Enum

# ============ Wire Types (Three-Wire Model) ============

WireType = Literal["json", "markdown", "text"]

# ============ Port Direction ============

PortDirection = Literal["input", "output"]

# ============ Data Types (Legacy, for backward compatibility) ============

DataType = Literal[
    "text", "user_input", "context", "search_result", "analysis",
    "draft", "final_text", "debug_info", "json", "memory",
    "media_asset", "video_composition", "ui_spec", "agent_tool",
    "business_data", "character_profile", "scene_state"
]

# ============ Localized Text ============

@dataclass
class LocalizedText:
    """Text with Chinese and English translations."""
    zh: str
    en: str
    
    def get(self, lang: str = "zh") -> str:
        return self.zh if lang == "zh" else self.en

# ============ Port Definition ============

@dataclass
class PortDefinition:
    """Port definition for a node."""
    id: str
    label: str
    direction: PortDirection
    wire_type: WireType
    schema_id: Optional[str] = None
    required: bool = False
    # For display
    label_i18n: Optional[LocalizedText] = None

# ============ Node Config Field ============

ConfigFieldKind = Literal[
    "text", "textarea", "number", "select", "tags",
    "boolean", "multiselect", "json", "secret", "model"
]

@dataclass
class ConfigFieldOption:
    """Option for select/multiselect fields."""
    label: LocalizedText
    value: str

@dataclass
class NodeConfigField:
    """Configuration field definition for a node."""
    key: str
    label: LocalizedText
    kind: ConfigFieldKind
    options: Optional[list[Union[str, ConfigFieldOption]]] = None
    required: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    placeholder: Optional[LocalizedText] = None
    help: Optional[LocalizedText] = None
    advanced: bool = False

# ============ Node Definition ============

PanelLayout = Literal["agent", "worldbook", "memory", "output", "preview", "generic"]

@dataclass
class NodeDefinition:
    """Definition of a ComfyUI node."""
    type: str
    label: str
    ports: list[PortDefinition]
    label_i18n: Optional[LocalizedText] = None
    category: Optional[str] = None
    description: Optional[str] = None
    description_i18n: Optional[LocalizedText] = None
    color: Optional[str] = None
    preview: Optional[str] = None
    preview_i18n: Optional[LocalizedText] = None
    default_config: Optional[dict[str, Any]] = None
    config_fields: Optional[list[NodeConfigField]] = None
    quick_add: bool = False
    panel_layout: PanelLayout = "generic"

# ============ Workflow Types ============

@dataclass
class WorkflowNode:
    """A node instance in a workflow."""
    id: str
    type: str
    position: dict[str, float]
    config: dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkflowEdge:
    """An edge connecting two nodes."""
    id: str
    source: str
    source_port: str
    target: str
    target_port: str

@dataclass
class WorkflowDefinition:
    """Complete workflow definition."""
    id: str
    name: str
    version: int
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]

# ============ Execution Types ============

@dataclass
class WorkflowRunContext:
    """Context passed during workflow execution."""
    run_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    abort_signal: Optional[Any] = None
    values: dict[str, Any] = field(default_factory=dict)

@dataclass
class NodeExecutionInput:
    """Input passed to a node executor."""
    node: WorkflowNode
    inputs: dict[str, Any]
    context: Optional[WorkflowRunContext] = None

@dataclass
class NodeExecutionOutput:
    """Output from a node executor."""
    outputs: dict[str, Any]
    metadata: Optional[dict[str, Any]] = None

# Node executor function type
NodeExecutor = Callable[[NodeExecutionInput], NodeExecutionOutput]

# ============ LLM Types ============

@dataclass
class LlmTokenUsage:
    """Token usage statistics."""
    input: int
    output: int
    cached_input: Optional[int] = None

@dataclass
class LlmToolDefinition:
    """A tool/function definition for LLM function calling."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class LlmToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: str  # JSON string of arguments

    def parse_arguments(self) -> dict[str, Any]:
        """Parse the arguments JSON string."""
        import json
        try:
            return json.loads(self.arguments) if self.arguments else {}
        except json.JSONDecodeError:
            return {}


@dataclass
class LlmCompletionInput:
    """Input for LLM completion."""
    model: str
    prompt: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout_ms: Optional[int] = None
    tools: Optional[list[LlmToolDefinition]] = None
    tool_choice: Optional[str] = None  # "auto", "none", or specific tool name


@dataclass
class LlmCompletionResult:
    """Result from LLM completion."""
    text: str
    token_usage: LlmTokenUsage
    finish_reason: Optional[str] = None
    provider_request_id: Optional[str] = None
    tool_calls: list[LlmToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        """Whether the LLM requested tool calls."""
        return len(self.tool_calls) > 0

# ============ Memory Types ============

@dataclass
class MemoryRecord:
    """A memory record in long-term storage."""
    id: str
    namespace: str
    content: str
    title: Optional[str] = None
    type: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    importance: Optional[float] = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentTurn:
    """A single turn in an agent session."""
    turn_index: int
    input: Any
    assistant_output: Any
    model_config: dict[str, Any] = field(default_factory=dict)
    token_usage: LlmTokenUsage = field(default_factory=lambda: LlmTokenUsage(0, 0))
    created_at: str = ""

@dataclass
class AgentSessionKey:
    """Isolation key for agent sessions."""
    tenant_id: str
    workflow_instance_id: str
    conversation_id: str
    agent_node_id: str
    branch_id: Optional[str] = None

@dataclass
class AgentSessionContext:
    """Agent session context with conversation history."""
    session_key: AgentSessionKey
    turns: list[AgentTurn] = field(default_factory=list)
    summary: Optional[str] = None
    estimated_tokens: int = 0
    truncated: bool = False

# ============ Worldbook Types ============

@dataclass
class WorldbookEntry:
    """A worldbook entry."""
    id: str
    content: str
    title: Optional[str] = None
    type: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    priority: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

@dataclass
class WorldbookSnapshot:
    """A snapshot of worldbook state."""
    resource_ref: str
    version: int
    entries: list[WorldbookEntry] = field(default_factory=list)
    total: int = 0

# ============ Retrieval Types ============

RetrievalStrategy = Literal["keyword", "bm25", "hybrid"]

@dataclass
class RetrievalDocument:
    """A document for retrieval."""
    id: str
    content: str
    title: Optional[str] = None
    type: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    priority: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class RetrievalHit:
    """A retrieval hit with score."""
    rank: int
    score: float
    source_index: int
    entry: RetrievalDocument
    matched_fields: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

@dataclass
class RetrievalResult:
    """Result from retrieval."""
    query: str
    strategy: RetrievalStrategy
    total_candidates: int
    total_after_filter: int
    total_matched: int
    returned: int
    hits: list[RetrievalHit] = field(default_factory=list)

# ============ Card Import Types ============

@dataclass
class ImportedGreeting:
    """An imported greeting from a character card."""
    greeting_id: str
    index: int
    label: Optional[str]
    content: str
    content_hash: str
    is_default: bool = False

@dataclass
class CardManifest:
    """Manifest of an imported character card."""
    schema_version: int
    card_id: str
    source_filename: str
    source_size_bytes: int
    source_hash: str
    imported_at: str
    spec: str
    name: str
    description: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    worldbook_entry_count: int = 0
    alternate_greeting_count: int = 0
    default_greeting_id: Optional[str] = None

@dataclass
class CardImportResult:
    """Result of importing a character card."""
    card_id: str
    already_existed: bool
    manifest: CardManifest
    greetings: list[ImportedGreeting] = field(default_factory=list)
    default_greeting_id: Optional[str] = None

# ============ Preset Types ============

@dataclass
class PromptFragment:
    """A fragment of prompt content with priority."""
    id: str
    content: str
    priority: int = 50

@dataclass
class OutputContract:
    """Contract for output format."""
    version: str
    mode: str
    slots: list[dict[str, Any]] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    allow_extra_text: bool = False

@dataclass
class RpPreset:
    """RP preset configuration."""
    version: str
    id: str
    name: str
    model: Optional[dict[str, Any]] = None
    prompt: Optional[dict[str, list[PromptFragment]]] = None
    output_contract: Optional[OutputContract] = None
    retry_policy: Optional[dict[str, int]] = None

# ============ Profile Types ============

@dataclass
class ProfileInputSlot:
    """Configuration for an input slot in a profile."""
    required: bool
    order: int
    json_renderer: bool = False

@dataclass
class ProfileModelDefaults:
    """Default model configuration for a profile."""
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout_ms: Optional[int] = None
    response_format: Optional[Literal["text", "json_object"]] = None

@dataclass
class SpecializedAgentProfile:
    """A specialized agent profile with system prompt and configuration."""
    profile_id: str
    label: LocalizedText
    description: LocalizedText
    foundational_system_prompt: str
    required_inputs: dict[str, ProfileInputSlot]
    input_order: dict[str, int]
    default_model_config: ProfileModelDefaults
    locked_fields: list[str] = field(default_factory=list)
    runtime_role: Optional[str] = None
    quality_tier: Optional[str] = None

# ============ Variable State Types (MVU) ============

@dataclass
class VariableStateSnapshot:
    """Snapshot of variable state for a card session."""
    card_id: str
    session_id: str
    slot: str
    revision: int
    values: dict[str, Any]
    state_hash: str
    created_at: str
    updated_at: str

# ============ Provider Types ============

@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""
    provider_id: str
    api_key: str
    base_url: str
    default_model: str
    models: list[str] = field(default_factory=list)

@dataclass
class ResolvedModelRequest:
    """Resolved model configuration for an LLM call."""
    provider_id: str
    model: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout_ms: Optional[int] = None
    response_format: Optional[str] = None
