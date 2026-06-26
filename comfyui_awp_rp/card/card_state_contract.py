"""
P4D-1: Card state contract for stateful card runtime.

Defines the data contracts for:
- CardState v1: persistent state per card+session
- WriterContract v1: bounded working set for the writer
- RoundSnapshot v1: short state snapshot per turn
- CandidateCardStatePatch v1: pending state updates
- ConditionAST: safe, declarative condition evaluation format

Design principles:
- Memory = what happened; State = what is now; Conditions = what's allowed
- Writer only sees the current working set, not full history/worldbook
- No JavaScript/EJS/eval/exec — only declarative AST conditions
- cardId + sessionId isolation
"""

from __future__ import annotations

import json
import re as _re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
# Schema IDs
# ═══════════════════════════════════════════════════════════════════════════

CARD_STATE_SCHEMA = "awp.rp.card-state.v1"
WRITER_CONTRACT_SCHEMA = "awp.rp.writer-contract.v1"
ROUND_SNAPSHOT_SCHEMA = "awp.rp.round-snapshot.v1"
CANDIDATE_PATCH_SCHEMA = "awp.rp.candidate-card-state-patch.v1"
CONDITION_EVAL_SCHEMA = "awp.rp.condition-evaluation.v1"
COMMIT_RESULT_SCHEMA = "awp.rp.card-state-commit-result.v1"


# ═══════════════════════════════════════════════════════════════════════════
# CardState v1 — persistent per card+session
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CardState:
    """Persistent state for a single card+session combination.

    Isolation: cardId + sessionId must uniquely identify a state.
    Variables: sourced from card initial state or explicit node input.
    EventFlags: which events have been consumed.
    ActiveStageIds: which story stages are currently active.
    SceneState: current location/time/characters.
    Diagnostics: initialization notes, missing variable warnings.
    """

    schemaId: str = CARD_STATE_SCHEMA
    cardId: str = ""
    sessionId: str = ""
    revision: int = 0
    variables: dict[str, Any] = field(default_factory=dict)
    eventFlags: dict[str, bool] = field(default_factory=dict)
    activeStageIds: list[str] = field(default_factory=list)
    sceneState: dict[str, Any] = field(default_factory=lambda: {
        "location": "",
        "time": "",
        "activeCharacterIds": [],
        "lastAcceptedTurn": "",
    })
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Any) -> "CardState":
        if not isinstance(data, dict):
            return cls()
        return cls(
            schemaId=str(data.get("schemaId", CARD_STATE_SCHEMA)),
            cardId=str(data.get("cardId", "")),
            sessionId=str(data.get("sessionId", "")),
            revision=int(data.get("revision", 0)),
            variables=dict(data.get("variables") or {}),
            eventFlags=dict(data.get("eventFlags") or {}),
            activeStageIds=list(data.get("activeStageIds") or []),
            sceneState=dict(data.get("sceneState") or {
                "location": "", "time": "",
                "activeCharacterIds": [], "lastAcceptedTurn": "",
            }),
            diagnostics=list(data.get("diagnostics") or []),
        )

    @classmethod
    def from_json(cls, text: str) -> "CardState":
        try:
            return cls.from_dict(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            return cls()

    def add_diagnostic(self, code: str, message: str, severity: str = "info") -> None:
        self.diagnostics.append({
            "code": code,
            "message": message,
            "severity": severity,
        })

    def is_initialized(self) -> bool:
        return bool(self.cardId) and bool(self.sessionId)


# ═══════════════════════════════════════════════════════════════════════════
# ConditionAST — safe declarative condition format
# ═══════════════════════════════════════════════════════════════════════════

# Supported operators for condition evaluation
SUPPORTED_OPERATORS = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in"}
SUPPORTED_COMBINATORS = {"all", "any", "not", "exists"}


@dataclass
class ConditionNode:
    """A single condition node in the AST.

    Can be either:
    - A leaf condition: {path, op, value}
    - A combinator: {all: [...]} / {any: [...]} / {not: ...} / {exists: path}
    """

    # Leaf condition fields
    path: str = ""
    op: str = ""
    value: Any = None

    # Combinator fields
    all: list["ConditionNode"] = field(default_factory=list)
    any: list["ConditionNode"] = field(default_factory=list)
    not_: Optional["ConditionNode"] = None  # field name is 'not_' to avoid Python keyword
    exists: str = ""

    def to_dict(self) -> dict[str, Any]:
        if self.all:
            return {"all": [c.to_dict() for c in self.all]}
        if self.any:
            return {"any": [c.to_dict() for c in self.any]}
        if self.not_ is not None:
            return {"not": self.not_.to_dict()}
        if self.exists:
            return {"exists": self.exists}
        # Leaf condition
        result: dict[str, Any] = {"path": self.path, "op": self.op}
        if self.value is not None:
            result["value"] = self.value
        return result

    @classmethod
    def from_dict(cls, data: Any) -> "ConditionNode":
        if not isinstance(data, dict):
            return cls()

        # Combinator: all
        if "all" in data and isinstance(data["all"], list):
            return cls(all=[cls.from_dict(c) for c in data["all"]])

        # Combinator: any
        if "any" in data and isinstance(data["any"], list):
            return cls(any=[cls.from_dict(c) for c in data["any"]])

        # Combinator: not
        if "not" in data:
            return cls(not_=cls.from_dict(data["not"]))

        # Combinator: exists
        if "exists" in data and isinstance(data["exists"], str):
            return cls(exists=data["exists"])

        # Leaf condition
        return cls(
            path=str(data.get("path", "")),
            op=str(data.get("op", "")),
            value=data.get("value"),
        )

    def is_combinator(self) -> bool:
        return bool(self.all or self.any or self.not_ is not None or bool(self.exists))

    def is_leaf(self) -> bool:
        return bool(self.path and self.op)


# ── Path safety validation ─────────────────────────────────────────────────

# Dangerous path segments that must never be resolved
_FORBIDDEN_PATH_SEGMENTS = frozenset({
    "__class__", "__dict__", "__globals__", "__builtins__",
    "__proto__", "__proto", "constructor", "prototype",
    "__import__", "__loader__", "__spec__",
})

# Pattern: reject bracket indexing, semicolons, expression concatenation
_DANGEROUS_PATH_CHARS = _re.compile(r'[\[\];(){}|&^~`!@#%+=]')


def _validate_path(path: str) -> tuple[bool, str]:
    """Validate a variable path is safe for resolution.

    Returns (valid, reason).
    Rejects: __class__, __dict__, __globals__, __proto__, constructor,
    bracket indexing, semicolons, expression concatenation.
    """
    if not path:
        return False, "empty_path"

    # Check for dangerous characters
    if _DANGEROUS_PATH_CHARS.search(path):
        return False, "dangerous_characters"

    # Split on dots and check each segment
    parts = path.split(".")
    for part in parts:
        if part in _FORBIDDEN_PATH_SEGMENTS:
            return False, f"forbidden_segment:{part}"
        # Reject empty segments (double dots)
        if not part:
            return False, "empty_segment"
        # Reject segments that look like function calls
        if "(" in part or ")" in part:
            return False, "function_call_syntax"

    return True, ""


def _resolve_json_path(obj: Any, path: str) -> tuple[Any, bool]:
    """Resolve a dotted path like 'data.character.favor' against a dict.

    Returns (value, found). Supports both dot notation and JSON Pointer (/).
    Includes safety validation to reject dangerous paths.
    """
    if not path:
        return None, False

    # Validate path safety
    valid, _ = _validate_path(path)
    if not valid:
        return None, False

    # Normalize: support both dot and slash notation
    if path.startswith("/"):
        parts = [p for p in path.split("/") if p]
    else:
        parts = path.split(".")

    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return None, False
        elif isinstance(current, list):
            try:
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None, False
            except (ValueError, IndexError):
                return None, False
        else:
            return None, False

    return current, True


def evaluate_condition(node: ConditionNode, state: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate a condition AST node against the current state.

    Returns (result, reason_code).
    reason_code is empty on success, or one of:
      - condition_false
      - missing_variable
      - unknown_path
      - unsupported_operator
    """
    # Combinator: all
    if node.all:
        for child in node.all:
            ok, reason = evaluate_condition(child, state)
            if not ok:
                return False, reason
        return True, ""

    # Combinator: any
    if node.any:
        for child in node.any:
            ok, reason = evaluate_condition(child, state)
            if ok:
                return True, ""
        return False, "condition_false"

    # Combinator: not
    if node.not_ is not None:
        ok, reason = evaluate_condition(node.not_, state)
        return (not ok, "" if not ok else "condition_false")

    # Combinator: exists
    if node.exists:
        _, found = _resolve_json_path(state, node.exists)
        if found:
            return True, ""
        return False, "missing_variable"

    # Leaf condition
    if not node.path:
        return False, "unknown_path"
    if node.op not in SUPPORTED_OPERATORS:
        return False, "unsupported_operator"

    actual, found = _resolve_json_path(state, node.path)
    if not found:
        return False, "missing_variable"

    expected = node.value

    try:
        result = False
        if node.op == "==":
            result = (actual == expected)
        elif node.op == "!=":
            result = (actual != expected)
        elif node.op == ">":
            result = (actual > expected)
        elif node.op == ">=":
            result = (actual >= expected)
        elif node.op == "<":
            result = (actual < expected)
        elif node.op == "<=":
            result = (actual <= expected)
        elif node.op == "in":
            if isinstance(expected, (list, tuple, set)):
                result = (actual in expected)
            else:
                return False, "unsupported_operator"
        elif node.op == "not_in":
            if isinstance(expected, (list, tuple, set)):
                result = (actual not in expected)
            else:
                return False, "unsupported_operator"
        else:
            return False, "unsupported_operator"
        return (result, "" if result else "condition_false")
    except TypeError:
        return False, "condition_false"


# ═══════════════════════════════════════════════════════════════════════════
# ConditionEntry — worldbook entry with conditions
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ConditionEntry:
    """A worldbook entry that may have activation conditions."""

    entryId: str = ""
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    entityScope: list[str] = field(default_factory=list)
    conditionAst: Optional[ConditionNode] = None
    rawCondition: str = ""  # Original condition text (for deferred entries)
    conditionFormat: str = ""  # "ast", "ejs", "getvar", "unknown"
    eventStage: str = ""  # Associated event stage ID
    priority: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "entryId": self.entryId,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "entityScope": self.entityScope,
            "rawCondition": self.rawCondition,
            "conditionFormat": self.conditionFormat,
            "eventStage": self.eventStage,
            "priority": self.priority,
        }
        if self.conditionAst:
            d["conditionAst"] = self.conditionAst.to_dict()
        return d


# ═══════════════════════════════════════════════════════════════════════════
# ConditionEvaluationResult
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ConditionEvaluationResult:
    """Result of evaluating all conditions in a worldbook."""

    schemaId: str = CONDITION_EVAL_SCHEMA
    activeEntries: list[dict[str, Any]] = field(default_factory=list)
    blockedEntries: list[dict[str, Any]] = field(default_factory=list)
    conditionEvaluation: list[dict[str, Any]] = field(default_factory=list)
    eligibleEventIds: list[str] = field(default_factory=list)
    blockedEventIds: list[str] = field(default_factory=list)
    activeStageIds: list[str] = field(default_factory=list)
    forbiddenStageMoves: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# ═══════════════════════════════════════════════════════════════════════════
# WriterContract v1 — bounded working set for the writer
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CastInfo:
    """Character identity and relationship bindings."""

    lockedCharacters: list[dict[str, Any]] = field(default_factory=list)
    userIdentity: dict[str, Any] = field(default_factory=dict)
    relationshipBindings: list[dict[str, Any]] = field(default_factory=list)
    aliases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StateInfo:
    """Current state summary for the writer."""

    variables: dict[str, Any] = field(default_factory=dict)
    activeStageIds: list[str] = field(default_factory=list)
    eligibleEventIds: list[str] = field(default_factory=list)
    forbiddenStageMoves: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SceneInfo:
    """Current scene state."""

    location: str = ""
    time: str = ""
    activeCharacterIds: list[str] = field(default_factory=list)
    lastAcceptedTurn: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContinuityInfo:
    """Continuity data: recent history, summary, open threads."""

    recentHistory: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    openThreads: list[dict[str, Any]] = field(default_factory=list)
    relevantFacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorldbookInfo:
    """Worldbook entries categorized for this turn."""

    pinnedCore: list[dict[str, Any]] = field(default_factory=list)
    conditionalActive: list[dict[str, Any]] = field(default_factory=list)
    retrievedDynamic: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutputRequirements:
    """Output format requirements for the writer."""

    minBodyChars: int = 800
    targetBodyChars: list[int] = field(default_factory=lambda: [900, 1200])
    excludeOptionsBlock: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BudgetInfo:
    """Token budget tracking."""

    historyChars: int = 0
    memoryChars: int = 0
    worldbookChars: int = 0
    totalEstimatedTokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriterContract:
    """Bounded working set for the writer per turn.

    The writer receives ONLY this contract + player_input.
    It must NOT re-read card, worldbook, or history internally.
    """

    schemaId: str = WRITER_CONTRACT_SCHEMA
    sessionId: str = ""
    cardId: str = ""
    cast: CastInfo = field(default_factory=CastInfo)
    state: StateInfo = field(default_factory=StateInfo)
    scene: SceneInfo = field(default_factory=SceneInfo)
    continuity: ContinuityInfo = field(default_factory=ContinuityInfo)
    worldbook: WorldbookInfo = field(default_factory=WorldbookInfo)
    outputRequirements: OutputRequirements = field(default_factory=OutputRequirements)
    budget: BudgetInfo = field(default_factory=BudgetInfo)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaId": self.schemaId,
            "sessionId": self.sessionId,
            "cardId": self.cardId,
            "cast": self.cast.to_dict(),
            "state": self.state.to_dict(),
            "scene": self.scene.to_dict(),
            "continuity": self.continuity.to_dict(),
            "worldbook": self.worldbook.to_dict(),
            "outputRequirements": self.outputRequirements.to_dict(),
            "budget": self.budget.to_dict(),
            "diagnostics": self.diagnostics,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Any) -> "WriterContract":
        if not isinstance(data, dict):
            return cls()
        cast_data = data.get("cast") or {}
        state_data = data.get("state") or {}
        scene_data = data.get("scene") or {}
        cont_data = data.get("continuity") or {}
        wb_data = data.get("worldbook") or {}
        out_data = data.get("outputRequirements") or {}
        budget_data = data.get("budget") or {}

        return cls(
            schemaId=str(data.get("schemaId", WRITER_CONTRACT_SCHEMA)),
            sessionId=str(data.get("sessionId", "")),
            cardId=str(data.get("cardId", "")),
            cast=CastInfo(
                lockedCharacters=list(cast_data.get("lockedCharacters") or []),
                userIdentity=dict(cast_data.get("userIdentity") or {}),
                relationshipBindings=list(cast_data.get("relationshipBindings") or []),
                aliases=list(cast_data.get("aliases") or []),
            ),
            state=StateInfo(
                variables=dict(state_data.get("variables") or {}),
                activeStageIds=list(state_data.get("activeStageIds") or []),
                eligibleEventIds=list(state_data.get("eligibleEventIds") or []),
                forbiddenStageMoves=list(state_data.get("forbiddenStageMoves") or []),
            ),
            scene=SceneInfo(
                location=str(scene_data.get("location") or ""),
                time=str(scene_data.get("time") or ""),
                activeCharacterIds=list(scene_data.get("activeCharacterIds") or []),
                lastAcceptedTurn=str(scene_data.get("lastAcceptedTurn") or ""),
            ),
            continuity=ContinuityInfo(
                recentHistory=list(cont_data.get("recentHistory") or []),
                summary=str(cont_data.get("summary") or ""),
                openThreads=list(cont_data.get("openThreads") or []),
                relevantFacts=list(cont_data.get("relevantFacts") or []),
            ),
            worldbook=WorldbookInfo(
                pinnedCore=list(wb_data.get("pinnedCore") or []),
                conditionalActive=list(wb_data.get("conditionalActive") or []),
                retrievedDynamic=list(wb_data.get("retrievedDynamic") or []),
                dropped=list(wb_data.get("dropped") or []),
            ),
            outputRequirements=OutputRequirements(
                minBodyChars=int(out_data.get("minBodyChars", 800)),
                targetBodyChars=list(out_data.get("targetBodyChars") or [900, 1200]),
                excludeOptionsBlock=bool(out_data.get("excludeOptionsBlock", True)),
            ),
            budget=BudgetInfo(
                historyChars=int(budget_data.get("historyChars", 0)),
                memoryChars=int(budget_data.get("memoryChars", 0)),
                worldbookChars=int(budget_data.get("worldbookChars", 0)),
                totalEstimatedTokens=int(budget_data.get("totalEstimatedTokens", 0)),
            ),
            diagnostics=list(data.get("diagnostics") or []),
        )

    @classmethod
    def from_json(cls, text: str) -> "WriterContract":
        try:
            return cls.from_dict(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            return cls()


# ═══════════════════════════════════════════════════════════════════════════
# CandidateCardStatePatch v1 — pending state updates
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CandidateCardStatePatch:
    """Candidate patch to card state, pending quality gate approval.

    Only committed when AWPSideEffectDecision.accepted == True.
    Operations must pass schema/path/type/range validation.
    """

    schemaId: str = CANDIDATE_PATCH_SCHEMA
    cardId: str = ""
    sessionId: str = ""
    sourceTurn: int = 0
    operations: list[dict[str, Any]] = field(default_factory=list)
    eventMarks: list[dict[str, Any]] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    commitPolicy: str = "pending"  # "pending" | "auto" | "manual"
    # P4D-2A: stable identity for idempotent replay + optimistic revision lock.
    # patchId: stable id for this exact candidate patch (dedup on replay).
    # expectedRevision: the revision this patch was authored against; the commit
    #   is rejected if the persisted revision has moved on (stale_revision).
    patchId: str = ""
    expectedRevision: int = -1  # -1 = not specified

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Any) -> "CandidateCardStatePatch":
        if not isinstance(data, dict):
            return cls()
        return cls(
            schemaId=str(data.get("schemaId", CANDIDATE_PATCH_SCHEMA)),
            cardId=str(data.get("cardId", "")),
            sessionId=str(data.get("sessionId", "")),
            sourceTurn=int(data.get("sourceTurn", 0)),
            operations=list(data.get("operations") or []),
            eventMarks=list(data.get("eventMarks") or []),
            provenance=list(data.get("provenance") or []),
            commitPolicy=str(data.get("commitPolicy", "pending")),
            patchId=str(data.get("patchId", "")),
            expectedRevision=int(data.get("expectedRevision", -1)),
        )

    @classmethod
    def from_json(cls, text: str) -> "CandidateCardStatePatch":
        try:
            return cls.from_dict(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            return cls()


# ═══════════════════════════════════════════════════════════════════════════
# Patch validation
# ═══════════════════════════════════════════════════════════════════════════

ALLOWED_PATCH_OPS = {"set", "add", "remove", "increment", "append", "replace"}
MAX_OPERATIONS_PER_PATCH = 50


def validate_candidate_patch(
    patch: CandidateCardStatePatch,
    current_state: Optional[CardState] = None,
) -> tuple[bool, list[str]]:
    """Validate a candidate patch against schema rules.

    Returns (valid, list_of_errors).
    """
    errors: list[str] = []

    if not patch.cardId:
        errors.append("missing cardId")
    if not patch.sessionId:
        errors.append("missing sessionId")
    if not patch.operations and not patch.eventMarks:
        errors.append("empty operations and eventMarks")

    if len(patch.operations) > MAX_OPERATIONS_PER_PATCH:
        errors.append(f"too many operations: {len(patch.operations)} > {MAX_OPERATIONS_PER_PATCH}")

    for i, op in enumerate(patch.operations):
        if not isinstance(op, dict):
            errors.append(f"operation[{i}] is not a dict")
            continue
        op_type = op.get("op")
        if op_type not in ALLOWED_PATCH_OPS:
            errors.append(f"operation[{i}].op={op_type!r} not in {ALLOWED_PATCH_OPS}")
        path = op.get("path")
        if not path or not isinstance(path, str):
            errors.append(f"operation[{i}].path is missing or invalid")

    if current_state and current_state.cardId and patch.cardId != current_state.cardId:
        errors.append(f"cardId mismatch: patch={patch.cardId} vs state={current_state.cardId}")
    if current_state and current_state.sessionId and patch.sessionId != current_state.sessionId:
        errors.append(f"sessionId mismatch: patch={patch.sessionId} vs state={current_state.sessionId}")

    return (len(errors) == 0, errors)


def apply_patch_operations(
    state: CardState,
    operations: list[dict[str, Any]],
) -> CardState:
    """Apply patch operations to a card state.

    Returns a new CardState with operations applied.
    """
    import copy
    new_state = CardState.from_dict(state.to_dict())
    new_state.revision = state.revision + 1

    for op in operations:
        if not isinstance(op, dict):
            continue
        op_type = op.get("op")
        path = op.get("path", "")
        value = op.get("value")

        if op_type == "set":
            _set_path(new_state.variables, path, value)
        elif op_type == "add":
            _set_path(new_state.variables, path, value)
        elif op_type == "remove":
            _remove_path(new_state.variables, path)
        elif op_type == "increment":
            current, found = _resolve_json_path(new_state.variables, path)
            if found and isinstance(current, (int, float)) and isinstance(value, (int, float)):
                _set_path(new_state.variables, path, current + value)
        elif op_type == "append":
            current, found = _resolve_json_path(new_state.variables, path)
            if found and isinstance(current, list):
                current.append(value)
            elif not found:
                _set_path(new_state.variables, path, [value])

    return new_state


def _set_path(obj: dict, path: str, value: Any) -> None:
    """Set a value at a dotted path in a nested dict."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _remove_path(obj: dict, path: str) -> None:
    """Remove a value at a dotted path in a nested dict."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]


# ═══════════════════════════════════════════════════════════════════════════
# P4D-2A: Strict formal commit patch application
# ═══════════════════════════════════════════════════════════════════════════
#
# This is deliberately SEPARATE from the greeting-bootstrap replace-or-add
# adapter (AWPCardStateInit._apply_initial_patches) and from the loose
# apply_patch_operations() helper.
#
# Greeting bootstrap: may use replace-or-add semantics for tavern initial
#   patch compatibility, limited to initialization, with diagnostics.
# Formal commit: MUST be strict, predictable, and atomic. `replace` on a
#   non-existent path is rejected; only `add` may create a new path. Any
#   invalid operation rejects the ENTIRE patch — no partial writes.
#
# Paths are rooted at an allowed state subtree:
#   variables / eventFlags / activeStageIds / sceneState
# Writing to protected fields (schemaId/cardId/sessionId/revision/diagnostics)
# or any other root is rejected.

ALLOWED_COMMIT_ROOTS = ("variables", "eventFlags", "activeStageIds", "sceneState")
PROTECTED_COMMIT_ROOTS = ("schemaId", "cardId", "sessionId", "revision", "diagnostics")

# Operations permitted in a formal commit patch. `set` is treated as a strict
# alias of `replace` (path must already exist). `add` creates a new path.
COMMIT_PATCH_OPS = {"replace", "set", "add", "remove", "increment", "append"}


def _normalize_rooted_path(path: str) -> tuple[str, list[str]]:
    """Normalize a patch path to (root, rest_parts).

    Accepts dot notation ('variables.score') or JSON Pointer ('/variables/score').
    Returns ("", []) for an empty path.
    """
    p = path.strip()
    # JSON Pointer form
    if p.startswith("/"):
        p = p.replace("/", ".")
    p = p.strip(".")
    if not p:
        return "", []
    parts = p.split(".")
    return parts[0], [seg for seg in parts[1:] if seg != ""]


def _resolve_strict(obj: Any, parts: list[str]) -> tuple[Any, bool]:
    """Resolve a dotted path within a subtree. Returns (value, found)."""
    cur = obj
    for part in parts:
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                return None, False
        elif isinstance(cur, list):
            try:
                idx = int(part)
            except (ValueError, TypeError):
                return None, False
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None, False
        else:
            return None, False
    return cur, True


def _set_existing_leaf(obj: Any, parts: list[str], value: Any) -> bool:
    """Set a leaf value where the full path must already exist.

    Returns True on success, False if the path (or a non-final segment) is absent.
    """
    if not parts:
        # Replacing the whole subtree object is not meaningful for a dict/list
        # root via this helper — callers handle root-level replaces separately.
        return False
    parent, found = _resolve_strict(obj, parts[:-1])
    if not found or not isinstance(parent, (dict, list)):
        return False
    leaf = parts[-1]
    if isinstance(parent, dict):
        if leaf not in parent:
            return False
        parent[leaf] = value
        return True
    # list
    try:
        idx = int(leaf)
    except (ValueError, TypeError):
        return False
    if 0 <= idx < len(parent):
        parent[idx] = value
        return True
    return False


def _add_new_leaf(obj: Any, parts: list[str], value: Any) -> tuple[bool, str]:
    """Create a new leaf path. Intermediate dicts are created only where absent;
    an existing non-dict intermediate is a type conflict (rejected).

    Returns (ok, reason).
    """
    if not parts:
        return False, "add_on_existing_path"
    cur = obj
    for part in parts[:-1]:
        if isinstance(cur, dict):
            if part in cur:
                if not isinstance(cur[part], dict):
                    return False, "add_intermediate_type_conflict"
                cur = cur[part]
            else:
                cur[part] = {}
                cur = cur[part]
        else:
            return False, "add_intermediate_type_conflict"
    leaf = parts[-1]
    if isinstance(cur, dict):
        if leaf in cur:
            return False, "add_on_existing_path"
        cur[leaf] = value
        return True, ""
    return False, "add_target_not_dict"


def _remove_existing_leaf(obj: Any, parts: list[str]) -> bool:
    """Remove a leaf that must exist. Returns True on success."""
    if not parts:
        return False
    parent, found = _resolve_strict(obj, parts[:-1])
    if not found or not isinstance(parent, (dict, list)):
        return False
    leaf = parts[-1]
    if isinstance(parent, dict):
        if leaf in parent:
            del parent[leaf]
            return True
        return False
    try:
        idx = int(leaf)
    except (ValueError, TypeError):
        return False
    if 0 <= idx < len(parent):
        del parent[idx]
        return True
    return False


def apply_commit_operations_strict(
    state: CardState,
    operations: list[dict[str, Any]],
) -> tuple[Optional[CardState], list[str], int]:
    """Strict, atomic patch application for formal CardState commit.

    Returns (new_state_or_None, errors, applied_count).
    - On ANY invalid operation: returns (None, errors, 0). The input state is
      not modified and no partial result is produced.
    - On success: returns (new_state, [], applied_count). new_state.revision is
      left equal to state.revision; the store bumps it inside the atomic
      transaction. applied_count counts operations that would be applied.

    Semantics:
      replace / set : path must already exist (else rejected).
      add           : path must NOT exist (creates it; only add may create).
      remove        : path must exist.
      increment     : path must exist and be numeric; value must be numeric.
      append        : path must exist and be a list.

    Paths must be rooted at one of ALLOWED_COMMIT_ROOTS. Protected fields and
    unknown roots are rejected.
    """
    import copy

    new_state = CardState.from_dict(state.to_dict())
    container = {
        "variables": new_state.variables,
        "eventFlags": new_state.eventFlags,
        "activeStageIds": new_state.activeStageIds,
        "sceneState": new_state.sceneState,
    }

    errors: list[str] = []
    applied = 0

    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            errors.append(f"operation[{i}] is not a dict")
            continue
        op_type = op.get("op")
        path = op.get("path", "")
        value = op.get("value")

        if op_type not in COMMIT_PATCH_OPS:
            errors.append(f"operation[{i}].op={op_type!r} not allowed in {COMMIT_PATCH_OPS}")
            continue
        if not isinstance(path, str) or not path.strip():
            errors.append(f"operation[{i}].path is missing or empty")
            continue

        valid, reason = _validate_path(path)
        if not valid:
            errors.append(f"operation[{i}].path unsafe: {reason}")
            continue

        root, rest = _normalize_rooted_path(path)
        if root in PROTECTED_COMMIT_ROOTS:
            errors.append(f"operation[{i}] targets protected field '{root}'")
            continue
        if root not in ALLOWED_COMMIT_ROOTS:
            errors.append(
                f"operation[{i}] path root '{root}' not in allowed subtrees {ALLOWED_COMMIT_ROOTS}"
            )
            continue

        target = container[root]

        if op_type in ("replace", "set"):
            if not rest:
                # Whole-subtree replace (e.g. replace entire sceneState).
                container[root] = value
                setattr(new_state, root, value)
            else:
                if not _set_existing_leaf(target, rest, value):
                    errors.append(
                        f"operation[{i}] {op_type} on non-existent path '{path}'"
                    )
                    continue
            applied += 1
            continue

        if op_type == "add":
            ok, reason = _add_new_leaf(target, rest, value)
            if not ok:
                errors.append(f"operation[{i}] add rejected on '{path}': {reason}")
                continue
            applied += 1
            continue

        if op_type == "remove":
            if not _remove_existing_leaf(target, rest):
                errors.append(f"operation[{i}] remove on non-existent path '{path}'")
                continue
            applied += 1
            continue

        if op_type == "increment":
            cur, found = _resolve_strict(target, rest)
            if not found:
                errors.append(f"operation[{i}] increment on non-existent path '{path}'")
                continue
            if isinstance(cur, bool) or not isinstance(cur, (int, float)):
                errors.append(f"operation[{i}] increment on non-numeric at '{path}'")
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"operation[{i}] increment value non-numeric")
                continue
            if not _set_existing_leaf(target, rest, cur + value):
                errors.append(f"operation[{i}] increment failed on '{path}'")
                continue
            applied += 1
            continue

        if op_type == "append":
            cur, found = _resolve_strict(target, rest)
            if not found:
                errors.append(f"operation[{i}] append on non-existent path '{path}'")
                continue
            if not isinstance(cur, list):
                errors.append(f"operation[{i}] append on non-list at '{path}'")
                continue
            cur.append(value)
            applied += 1
            continue

    if errors:
        return (None, errors, 0)

    return (new_state, [], applied)


def compute_patch_hash(patch: "CandidateCardStatePatch") -> str:
    """Deterministic hash of the patch's mutable content for idempotency checks.

    Only operations + eventMarks are hashed (the parts that change state).
    patchId, cardId, sessionId, provenance, commitPolicy are excluded so that
    a replay of the same logical patch is recognized regardless of metadata.
    """
    import hashlib
    payload = {
        "operations": patch.operations,
        "eventMarks": patch.eventMarks,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# Safe Legacy Condition Adapter
# ═══════════════════════════════════════════════════════════════════════════

# Allowed comparison operators
_LEGACY_OPS = {"==", "===", "!=", "!==", ">", ">=", "<", "<="}

# Operator translation: EJS/JS → AST
_OP_TRANSLATE = {
    "==": "==",
    "===": "==",
    "!=": "!=",
    "!==": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}

# Pattern: getvar('PATH') OP LITERAL
_GETVAR_CMP = _re.compile(
    r"""getvar\(\s*['"]([^'"]+)['"]\s*\)\s*(===?|!==?|>=?|<=?)\s*(.+?)\s*$"""
)

# Pattern: standalone getvar existence check  getvar('PATH') === undefined
_GETVAR_UNDEF = _re.compile(
    r"""getvar\(\s*['"]([^'"]+)['"]\s*\)\s*===?\s*undefined\s*$"""
)


def _parse_literal(text: str) -> Any:
    """Parse a literal value from EJS/JS condition text.

    Supports: integers, floats, true, false, null, quoted strings.
    Returns None if not a recognized literal (caller should treat as unsupported).
    """
    text = text.strip().rstrip(")").strip()

    # Boolean
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None

    # Integer
    try:
        return int(text)
    except ValueError:
        pass

    # Float
    try:
        return float(text)
    except ValueError:
        pass

    # Quoted string (single or double)
    if (text.startswith("'") and text.endswith("'")) or \
       (text.startswith('"') and text.endswith('"')):
        return text[1:-1]

    # Not a recognized literal
    return None


def _translate_single_getvar(condition_text: str) -> tuple[Optional[dict], str]:
    """Translate a single getvar comparison to AST leaf node.

    Returns (ast_dict_or_None, reason).
    reason is empty on success, or a reasonCode string.
    """
    text = condition_text.strip()

    # Check for undefined check: getvar('path') === undefined
    undef_match = _GETVAR_UNDEF.match(text)
    if undef_match:
        path = undef_match.group(1)
        valid, reason = _validate_path(path)
        if not valid:
            return None, f"unsafe_path:{reason}"
        # "=== undefined" means the variable does NOT exist.
        # Translate to: not exists
        return {"not": {"exists": path}}, ""

    # Check for comparison: getvar('path') OP literal
    cmp_match = _GETVAR_CMP.match(text)
    if not cmp_match:
        return None, "unsupported_condition_syntax"

    path = cmp_match.group(1)
    valid, reason = _validate_path(path)
    if not valid:
        return None, f"unsafe_path:{reason}"
    op = cmp_match.group(2)
    value_text = cmp_match.group(3).strip()

    if op not in _LEGACY_OPS:
        return None, "unsupported_operator"

    ast_op = _OP_TRANSLATE.get(op)
    if not ast_op:
        return None, "unsupported_operator"

    value = _parse_literal(value_text)
    if value is None and value_text not in ("null", "true", "false"):
        # Couldn't parse as literal
        return None, "unsupported_literal"

    return {"path": path, "op": ast_op, "value": value}, ""


def _split_condition_chain(text: str) -> list[str]:
    """Split a condition string on && and || while respecting nesting.

    Returns list of (operator, atom) tuples. First atom has operator ''.
    """
    atoms: list[str] = []
    current = ""
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif depth == 0 and text[i:i+2] == "&&":
            atoms.append(current.strip())
            current = ""
            i += 2
            continue
        elif depth == 0 and text[i:i+2] == "||":
            atoms.append(current.strip())
            current = ""
            i += 2
            continue
        else:
            current += ch
        i += 1
    if current.strip():
        atoms.append(current.strip())
    return atoms


def _detect_combinator(text: str) -> str:
    """Detect whether the condition uses && or || at top level."""
    # Simple detection: check for && or || outside parentheses
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            if text[i:i+2] == "&&":
                return "all"
            if text[i:i+2] == "||":
                return "any"
    return "single"


def translate_legacy_condition(condition_text: str) -> tuple[Optional[ConditionNode], str]:
    """Translate a legacy EJS/getvar condition string to a ConditionNode AST.

    Only translates whitelisted patterns:
    - getvar('PATH') OP LITERAL
    - getvar('PATH') === undefined
    - Compound: getvar(...) OP LITERAL && getvar(...) OP LITERAL
    - Compound: getvar(...) OP LITERAL || getvar(...) OP LITERAL
    - Negation: !getvar(...) OP LITERAL (simplified)

    Returns (ConditionNode_or_None, status).
    status is 'translated' on success, or 'deferred_unsupported' on failure.
    """
    if not condition_text or not condition_text.strip():
        return None, "deferred_unsupported"

    text = condition_text.strip()

    # Strip outer parentheses if present
    while text.startswith("(") and text.endswith(")"):
        # Verify they match
        depth = 0
        matched = True
        for i, ch in enumerate(text):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth == 0 and i < len(text) - 1:
                matched = False
                break
        if matched:
            text = text[1:-1].strip()
        else:
            break

    # Detect combinator
    combinator = _detect_combinator(text)

    if combinator == "single":
        # Single condition
        # Check for negation
        if text.startswith("!"):
            inner = text[1:].strip()
            node, reason = _translate_single_getvar(inner)
            if node is None:
                return None, "deferred_unsupported"
            return ConditionNode(not_=ConditionNode.from_dict(node)), "translated"

        node_dict, reason = _translate_single_getvar(text)
        if node_dict is None:
            return None, "deferred_unsupported"
        return ConditionNode.from_dict(node_dict), "translated"

    # Compound: split on && or ||
    atoms = _split_condition_chain(text)
    if len(atoms) < 2:
        return None, "deferred_unsupported"

    children: list[ConditionNode] = []
    for atom in atoms:
        atom = atom.strip()
        if not atom:
            continue
        # Check for negation
        if atom.startswith("!"):
            inner = atom[1:].strip()
            node_dict, reason = _translate_single_getvar(inner)
            if node_dict is None:
                return None, "deferred_unsupported"
            children.append(ConditionNode(not_=ConditionNode.from_dict(node_dict)))
        else:
            node_dict, reason = _translate_single_getvar(atom)
            if node_dict is None:
                return None, "deferred_unsupported"
            children.append(ConditionNode.from_dict(node_dict))

    if not children:
        return None, "deferred_unsupported"

    if combinator == "all":
        return ConditionNode(all=children), "translated"
    elif combinator == "any":
        return ConditionNode(any=children), "translated"

    return None, "deferred_unsupported"


def translate_legacy_ejs_conditions(
    content: str,
    branch_group_id: str = "",
) -> list[dict[str, Any]]:
    """Scan EJS content and translate all whitelisted if/else-if conditions.

    Returns a list of dicts:
    {
        "branch_index": int,
        "branchGroupId": str,  # identifies the if/else-if chain
        "branchOrder": int,    # 0-based order within the chain (first match wins)
        "raw_condition": str,
        "ast": dict_or_None,
        "status": "translated" | "deferred_unsupported",
        "reason": str,
    }

    Branch semantics: In an if/else-if chain, only the FIRST matching branch
    should be active. branchOrder preserves the chain order so evaluators
    can implement "first match wins" logic.

    Safety: If a bare ``else`` (without ``if``) is detected in a branch group,
    ALL branches in that group are marked deferred_unsupported with reason
    "unsupported_else_branch". This prevents partial activation of a chain
    where the else clause would be silently ignored.
    """
    results: list[dict[str, Any]] = []

    # Extract if/else-if blocks from EJS content
    # Pattern: <%_ if (CONDITION) { _%>  or  <%_ } else if (CONDITION) { _%>
    pattern = _re.compile(
        r"<%[_\s]*(?:\}\s*)?(?:else\s+)?if\s*\(([^{]+?)\)\s*\{[^%]*%>",
        _re.IGNORECASE,
    )

    # Detect bare ``else`` blocks (not followed by ``if``)
    # Pattern: <%_ } else { _%>  or  <%_ else { _%>
    bare_else_pattern = _re.compile(
        r"<%[_\s]*(?:\}\s*)?else\s*\{[^%]*%>",
        _re.IGNORECASE,
    )

    # Generate a group ID from content hash if not provided
    if not branch_group_id:
        import hashlib
        branch_group_id = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]

    # Check for bare else — if present, entire group is unsupported
    has_bare_else = bool(bare_else_pattern.search(content))

    # Also check for any ``else if`` with non-whitelisted conditions
    # by scanning for else-if blocks that our main regex didn't capture
    # (e.g., else if with complex expressions)
    else_if_pattern = _re.compile(
        r"<%[_\s]*(?:\}\s*)?else\s+if\s*\(([^{]+?)\)\s*\{[^%]*%>",
        _re.IGNORECASE,
    )
    main_matches = list(pattern.finditer(content))
    else_if_matches = list(else_if_pattern.finditer(content))

    # If there are else-if matches that our main pattern didn't catch,
    # it means they have unsupported syntax
    has_unsupported_else_if = len(else_if_matches) > len(main_matches)

    for i, match in enumerate(main_matches):
        raw_condition = match.group(1).strip()
        # Strip trailing ) if it's part of the EJS syntax
        if raw_condition.endswith(")"):
            raw_condition = raw_condition[:-1].strip()

        ast_node, status = translate_legacy_condition(raw_condition)

        # If bare else or unsupported else-if detected, override status
        if has_bare_else or has_unsupported_else_if:
            status = "deferred_unsupported"
            reason = "unsupported_else_branch"
            ast_node = None
        else:
            reason = "" if status == "translated" else status

        result: dict[str, Any] = {
            "branch_index": i,
            "branchGroupId": branch_group_id,
            "branchOrder": i,
            "raw_condition": raw_condition,
            "ast": ast_node.to_dict() if ast_node else None,
            "status": status,
            "reason": reason,
        }
        results.append(result)

    return results
