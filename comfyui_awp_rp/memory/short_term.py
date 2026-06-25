"""
Short-term memory (Agent Session) management.

Agent Session represents ONE agent node's continuous conversation context.
It tracks conversation turns, manages token budget, and supports auto-summarization.

Isolation: tenantId + workflowInstanceId + conversationId + agentNodeId (+ branchId)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.types import (
    AgentSessionContext,
    AgentSessionKey,
    AgentTurn,
    LlmTokenUsage,
)
from ..core.store import SQLiteStore, get_store


@dataclass
class SessionConfig:
    """Per-agent session configuration."""
    mode: str = "stateless"  # "stateless" or "stateful"
    max_turns: int = 20
    max_tokens: int = 16000
    include_tool_calls: bool = True
    auto_summarize: bool = False


DEFAULT_SESSION_CONFIG = SessionConfig()


class ShortTermMemory:
    """Short-term memory manager for agent sessions."""
    
    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
    
    def load(self, key: AgentSessionKey) -> Optional[AgentSessionContext]:
        """Load an agent session context."""
        return self._store.load_session(key)
    
    def save(self, context: AgentSessionContext) -> None:
        """Save an agent session context."""
        self._store.save_session(context)
    
    def delete(self, key: AgentSessionKey) -> None:
        """Delete an agent session."""
        self._store.delete_session(key)
    
    def append_turn(
        self,
        key: AgentSessionKey,
        input_data: Any,
        assistant_output: Any,
        model_config: dict[str, Any],
        token_usage: LlmTokenUsage,
    ) -> AgentSessionContext:
        """Append a new turn to the session."""
        context = self.load(key)
        
        if context is None:
            # Create new session
            context = AgentSessionContext(
                session_key=key,
                turns=[],
                summary=None,
                estimated_tokens=0,
                truncated=False,
            )
        
        # Create new turn
        new_turn = AgentTurn(
            turn_index=len(context.turns) + 1,
            input=input_data,
            assistant_output=assistant_output,
            model_config=model_config,
            token_usage=token_usage,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        
        context.turns.append(new_turn)
        
        # Update token estimate
        turn_text = f"{input_data}{assistant_output}"
        new_tokens = len(turn_text) // 4  # Rough estimate
        context.estimated_tokens += new_tokens
        
        self.save(context)
        return context
    
    def get_context_for_prompt(
        self,
        key: AgentSessionKey,
        max_tokens: int,
        protected_tokens: int = 0,
    ) -> tuple[list[AgentTurn], Optional[str], bool]:
        """Get session context for prompt assembly.
        
        Returns: (included_turns, summary, truncated)
        """
        context = self.load(key)
        
        if context is None:
            return [], None, False
        
        available = max_tokens - protected_tokens
        if available <= 0:
            return [], context.summary, True
        
        # Include turns from newest to oldest, within budget
        included: list[AgentTurn] = []
        used = 0
        
        for turn in reversed(context.turns):
            turn_text = f"{turn.input}{turn.assistant_output}"
            turn_tokens = len(turn_text) // 4
            
            if used + turn_tokens > available:
                break
            
            included.insert(0, turn)  # Insert at beginning to maintain order
            used += turn_tokens
        
        truncated = len(included) < len(context.turns)
        
        return included, context.summary, truncated
    
    def summarize(self, key: AgentSessionKey, summary: str) -> None:
        """Set a summary for the session (for when turns are truncated)."""
        context = self.load(key)
        if context:
            context.summary = summary
            context.truncated = True
            self.save(context)


class AgentSessionManager:
    """High-level manager for agent sessions with configuration."""
    
    def __init__(
        self,
        store: Optional[SQLiteStore] = None,
        config: Optional[SessionConfig] = None,
    ):
        self._memory = ShortTermMemory(store)
        self._config = config or DEFAULT_SESSION_CONFIG
    
    def create_key(
        self,
        tenant_id: str,
        workflow_instance_id: str,
        conversation_id: str,
        agent_node_id: str,
        branch_id: Optional[str] = None,
    ) -> AgentSessionKey:
        """Create a session key."""
        return AgentSessionKey(
            tenant_id=tenant_id,
            workflow_instance_id=workflow_instance_id,
            conversation_id=conversation_id,
            agent_node_id=agent_node_id,
            branch_id=branch_id,
        )
    
    def get_or_create(self, key: AgentSessionKey) -> AgentSessionContext:
        """Get existing session or create new one."""
        context = self._memory.load(key)
        if context is None:
            context = AgentSessionContext(
                session_key=key,
                turns=[],
                summary=None,
                estimated_tokens=0,
                truncated=False,
            )
            self._memory.save(context)
        return context
    
    def record_turn(
        self,
        key: AgentSessionKey,
        input_data: Any,
        assistant_output: Any,
        model_config: dict[str, Any],
        token_usage: LlmTokenUsage,
    ) -> AgentSessionContext:
        """Record a conversation turn."""
        return self._memory.append_turn(
            key, input_data, assistant_output, model_config, token_usage
        )
    
    def get_prompt_context(
        self,
        key: AgentSessionKey,
        protected_tokens: int = 0,
    ) -> tuple[list[AgentTurn], Optional[str], bool]:
        """Get context for prompt assembly."""
        return self._memory.get_context_for_prompt(
            key,
            max_tokens=self._config.max_tokens,
            protected_tokens=protected_tokens,
        )
    
    def should_summarize(self, key: AgentSessionKey) -> bool:
        """Check if session needs summarization."""
        if not self._config.auto_summarize:
            return False
        
        context = self._memory.load(key)
        if context is None:
            return False
        
        return (
            len(context.turns) >= self._config.max_turns or
            context.estimated_tokens >= self._config.max_tokens
        )

    def reroll_last(self, key: AgentSessionKey) -> Optional[str]:
        """Delete the last turn and return the user input for regeneration.

        Returns the user's input text that was paired with the deleted turn,
        or None if there are no turns to reroll.
        """
        context = self._memory.load(key)
        if not context or not context.turns:
            return None

        last = context.turns[-1]

        # Refuse to reroll if last turn has no user input (e.g., opening)
        if not last.input:
            return None

        user_text = str(last.input)
        context.turns.pop()
        context.estimated_tokens = max(0, context.estimated_tokens - len(user_text) // 4)
        self._memory.save(context)
        return user_text

    def delete_turns_from(self, key: AgentSessionKey, from_index: int) -> int:
        """Delete all turns with index >= from_index.

        Returns the number of turns deleted.
        """
        context = self._memory.load(key)
        if not context:
            return 0

        initial_count = len(context.turns)
        context.turns = [t for t in context.turns if t.turn_index < from_index]
        deleted = initial_count - len(context.turns)

        if deleted > 0:
            # Recalculate estimated tokens
            context.estimated_tokens = sum(
                (len(str(t.input or "")) + len(str(t.assistant_output or ""))) // 4
                for t in context.turns
            )
            self._memory.save(context)

        return deleted
