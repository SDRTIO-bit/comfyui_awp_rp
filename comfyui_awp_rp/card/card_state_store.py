"""
Card state persistent storage.

Uses the existing SQLiteStore's database connection.
Stores full CardState JSON per card_id + session_id.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.store import SQLiteStore, get_store
from .card_state_contract import CardState, CARD_STATE_SCHEMA


class CardStateStore:
    """Persistent storage for CardState objects.

    Reuses the existing SQLite database but with a dedicated table
    for card state (not the same as variable_state which is MVU-only).
    """

    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the card_state table if it doesn't exist."""
        with self._store._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS card_state (
                    card_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (card_id, session_id)
                )
            """)

    def load(self, card_id: str, session_id: str) -> Optional[CardState]:
        """Load a card state by card_id + session_id."""
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM card_state WHERE card_id = ? AND session_id = ?",
                (card_id, session_id),
            ).fetchone()
            if not row:
                return None
            return CardState.from_json(row["state_json"])

    def save(self, state: CardState) -> None:
        """Save a card state. Upsert semantics."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._store._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO card_state
                (card_id, session_id, state_json, revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                state.cardId,
                state.sessionId,
                state.to_json(),
                state.revision,
                now,
                now,
            ))

    def exists(self, card_id: str, session_id: str) -> bool:
        """Check if a card state exists."""
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM card_state WHERE card_id = ? AND session_id = ?",
                (card_id, session_id),
            ).fetchone()
            return row is not None

    def delete(self, card_id: str, session_id: str) -> bool:
        """Delete a card state."""
        with self._store._connect() as conn:
            result = conn.execute(
                "DELETE FROM card_state WHERE card_id = ? AND session_id = ?",
                (card_id, session_id),
            )
            return result.rowcount > 0
