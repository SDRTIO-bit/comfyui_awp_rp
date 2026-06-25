"""MVU (MagVarUpdate) subsystem for AWP RP.

Core variable engine ported from oh-story-claudecode, adapted for
ComfyUI-native execution. No external dependencies beyond Python stdlib.

Components:
  engine   — Command extraction, execution, schema generation, validation
  matcher  — Variable-change-driven worldbook entry matching
  checker  — Variable checklist generation for AI generation step
"""

from .engine import (
    Command,
    SchemaNode,
    extract_commands,
    execute_commands,
    generate_schema,
    validate_command,
    compute_var_diff,
    audit_variables,
    compute_current_variables,
    apply_variables_to_turn,
)
from .matcher import match_worldbook_by_variables, extract_topics_from_changes
from .checker import generate_variable_checklist

__all__ = [
    "Command", "SchemaNode",
    "extract_commands", "execute_commands",
    "generate_schema", "validate_command",
    "compute_var_diff", "audit_variables",
    "compute_current_variables", "apply_variables_to_turn",
    "match_worldbook_by_variables", "extract_topics_from_changes",
    "generate_variable_checklist",
]
