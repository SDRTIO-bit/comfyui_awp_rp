"""
Greeting management for character cards.

Handles greeting selection, initialization, and session setup.
"""

from typing import Optional

from ..core.types import ImportedGreeting
from ..core.store import SQLiteStore, get_store


class GreetingManager:
    """Manages greetings for character cards."""
    
    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
    
    def get_greetings(self, card_id: str) -> list[ImportedGreeting]:
        """Get all greetings for a card."""
        card = self._store.load_card(card_id)
        if not card:
            return []
        
        greetings_data = card.get("greetings", [])
        return [
            ImportedGreeting(
                greeting_id=g["greeting_id"],
                index=g["index"],
                label=g.get("label"),
                content=g["content"],
                content_hash=g.get("content_hash", ""),
                is_default=g.get("is_default", False),
            )
            for g in greetings_data
        ]
    
    def get_default_greeting(self, card_id: str) -> Optional[ImportedGreeting]:
        """Get the default greeting for a card.

        Falls back to the first substantial greeting if the default (g0)
        is too short (under 30 chars) — some cards use g0 as an author
        tag or label rather than a real opening.
        """
        greetings = self.get_greetings(card_id)
        if not greetings:
            return None

        MIN_LENGTH = 30

        # First try the marked default, but only if it's substantial
        for g in greetings:
            if g.is_default and g.content and len(g.content.strip()) >= MIN_LENGTH:
                return g

        # Default was too short — fall back to first substantial greeting
        for g in greetings:
            if g.content and len(g.content.strip()) >= MIN_LENGTH:
                return g

        # Everything too short — return the longest available
        best = max(greetings, key=lambda g: len(g.content or ""))
        return best
    
    def get_greeting_by_id(
        self,
        card_id: str,
        greeting_id: str,
    ) -> Optional[ImportedGreeting]:
        """Get a specific greeting by ID."""
        greetings = self.get_greetings(card_id)
        for g in greetings:
            if g.greeting_id == greeting_id:
                return g
        return None
    
    def select_greeting(
        self,
        card_id: str,
        greeting_id: Optional[str] = None,
    ) -> Optional[ImportedGreeting]:
        """Select a greeting for a session.
        
        If greeting_id is provided, returns that greeting.
        Otherwise returns the default greeting.
        """
        if greeting_id:
            return self.get_greeting_by_id(card_id, greeting_id)
        return self.get_default_greeting(card_id)
    
    def initialize_session_with_greeting(
        self,
        card_id: str,
        session_id: str,
        greeting_id: Optional[str] = None,
    ) -> Optional[str]:
        """Initialize a session with a greeting.
        
        Returns the greeting content, or None if no greeting found.
        This sets up the initial assistant message in the session.
        """
        greeting = self.select_greeting(card_id, greeting_id)
        if not greeting:
            return None
        
        # The greeting content becomes the initial assistant message
        # This will be handled by the session manager
        return greeting.content
