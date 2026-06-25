"""
Variable state management for MVU (Model-View-Update).

This module provides the infrastructure for variable state tracking.
Currently, variable execution is NOT supported (runtimeStatus: unsupported-runtime).
The module stores variable state and evaluates conditions, but does not
execute scripts or variable updates.

Future: When MVU runtime is enabled, this module will:
1. Execute JSON Patch operations on variable state
2. Evaluate conditions to activate deferred worldbook entries
3. Track variable changes across turns
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.types import VariableStateSnapshot
from ..core.store import SQLiteStore, get_store


@dataclass
class VariableCondition:
    """A condition for activating deferred entries."""
    kind: str  # "equals", "notEquals", "greaterThan", etc.
    path: str  # JSON Pointer
    value: Any


@dataclass
class ConditionEvaluationResult:
    """Result of evaluating conditions."""
    activated_entry_ids: list[str]
    deferred_entry_ids: list[str]
    rejected_conditions: list[dict[str, str]]
    evaluated_revision: int
    evaluated_at: str


class VariableStateManager:
    """Manages variable state for character cards.
    
    Note: This manager currently only stores state and evaluates conditions.
    It does NOT execute variable updates or scripts.
    """
    
    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
    
    def get_state(
        self,
        card_id: str,
        session_id: str,
        slot: str = "default",
    ) -> Optional[VariableStateSnapshot]:
        """Get variable state for a card session."""
        return self._store.load_variable_state(card_id, session_id, slot)
    
    def initialize_state(
        self,
        card_id: str,
        session_id: str,
        initial_values: dict[str, Any],
        slot: str = "default",
    ) -> VariableStateSnapshot:
        """Initialize variable state for a new session."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        snapshot = VariableStateSnapshot(
            card_id=card_id,
            session_id=session_id,
            slot=slot,
            revision=0,
            values=initial_values,
            state_hash=self._compute_hash(initial_values),
            created_at=now,
            updated_at=now,
        )
        
        self._store.save_variable_state(snapshot)
        return snapshot
    
    def update_state(
        self,
        card_id: str,
        session_id: str,
        new_values: dict[str, Any],
        slot: str = "default",
    ) -> Optional[VariableStateSnapshot]:
        """Update variable state.
        
        Note: This is a direct update, NOT a JSON Patch execution.
        Future: When MVU runtime is enabled, this will process patches.
        """
        current = self.get_state(card_id, session_id, slot)
        if not current:
            return None
        
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Merge values
        merged = {**current.values, **new_values}
        
        snapshot = VariableStateSnapshot(
            card_id=card_id,
            session_id=session_id,
            slot=slot,
            revision=current.revision + 1,
            values=merged,
            state_hash=self._compute_hash(merged),
            created_at=current.created_at,
            updated_at=now,
        )
        
        self._store.save_variable_state(snapshot)
        return snapshot
    
    def evaluate_conditions(
        self,
        card_id: str,
        session_id: str,
        deferred_entries: list[dict[str, Any]],
        slot: str = "default",
    ) -> ConditionEvaluationResult:
        """Evaluate conditions against current variable state.
        
        This checks which deferred worldbook entries should be activated
        based on the current variable state.
        
        Args:
            card_id: Character card ID
            session_id: Session ID
            deferred_entries: List of deferred entries with conditions
            slot: Variable state slot
        
        Returns:
            ConditionEvaluationResult with activated/deferred entry IDs
        """
        snapshot = self.get_state(card_id, session_id, slot)
        
        activated: list[str] = []
        deferred: list[str] = []
        rejected: list[dict[str, str]] = []
        
        for entry in deferred_entries:
            entry_id = str(entry.get("sourceEntryUid", ""))
            condition_data = entry.get("conditionAst")
            
            if not condition_data:
                # No condition AST - stays deferred
                deferred.append(entry_id)
                rejected.append({
                    "sourceEntryUid": entry_id,
                    "code": "no-ast",
                })
                continue
            
            # Evaluate the condition
            try:
                condition = VariableCondition(
                    kind=condition_data.get("kind", ""),
                    path=condition_data.get("path", ""),
                    value=condition_data.get("value"),
                )
                
                if snapshot and self._evaluate_condition(condition, snapshot.values):
                    activated.append(entry_id)
                else:
                    deferred.append(entry_id)
            except Exception as e:
                deferred.append(entry_id)
                rejected.append({
                    "sourceEntryUid": entry_id,
                    "code": f"evaluation-error: {str(e)[:50]}",
                })
        
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        return ConditionEvaluationResult(
            activated_entry_ids=activated,
            deferred_entry_ids=deferred,
            rejected_conditions=rejected,
            evaluated_revision=snapshot.revision if snapshot else 0,
            evaluated_at=now,
        )
    
    def _evaluate_condition(
        self,
        condition: VariableCondition,
        values: dict[str, Any],
    ) -> bool:
        """Evaluate a single condition against values."""
        # Resolve the path to get the actual value
        actual = self._resolve_path(values, condition.path)
        if actual is None:
            return False
        
        expected = condition.value
        
        if condition.kind == "equals":
            return actual == expected
        elif condition.kind == "notEquals":
            return actual != expected
        elif condition.kind == "greaterThan":
            return isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and actual > expected
        elif condition.kind == "lessThan":
            return isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and actual < expected
        elif condition.kind == "greaterOrEqual":
            return isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and actual >= expected
        elif condition.kind == "lessOrEqual":
            return isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and actual <= expected
        elif condition.kind == "boolean":
            return isinstance(actual, bool) and actual == expected
        
        return False
    
    def _resolve_path(self, values: dict[str, Any], path: str) -> Any:
        """Resolve a JSON Pointer path to a value."""
        if not path.startswith("/"):
            return None
        
        parts = path[1:].split("/")
        current: Any = values
        
        for part in parts:
            # Decode JSON Pointer escapes
            part = part.replace("~1", "/").replace("~0", "~")
            
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    index = int(part)
                    current = current[index] if 0 <= index < len(current) else None
                except ValueError:
                    return None
            else:
                return None
            
            if current is None:
                return None
        
        return current
    
    def _compute_hash(self, values: dict[str, Any]) -> str:
        """Compute a hash of the values for change detection."""
        content = json.dumps(values, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:32]
