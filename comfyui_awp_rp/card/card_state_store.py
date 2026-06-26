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
            # P4D-2A: idempotent-replay / patch-id-conflict log.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS card_state_patch_log (
                    card_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    patch_id TEXT NOT NULL,
                    patch_hash TEXT NOT NULL,
                    applied_revision INTEGER NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (card_id, session_id, patch_id)
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

    # ═══════════════════════════════════════════════════════════════════════════
    # P4D-2A: Atomic deterministic commit
    # ═══════════════════════════════════════════════════════════════════════════

    def commit_patch(
        self,
        card_id: str,
        session_id: str,
        new_state: CardState,
        expected_revision: int,
        patch_id: str,
        patch_hash: str,
    ) -> dict[str, Any]:
        """Atomically commit a validated candidate patch.

        All checks and the write happen inside ONE SQLite transaction
        (BEGIN IMMEDIATE) so revision comparison, patch-id dedup, revision
        bump, and patch-log insert are atomic. No partial writes are possible.

        Idempotency rule (checked BEFORE the revision check, so graph re-runs
        are recognized): if (card_id, session_id, patch_id) is already logged,
          - same patch_hash → idempotent_replay (no rewrite, revision unchanged)
          - different patch_hash → patch_id_conflict (rejected)

        Returns a commit-result dict (without schemaId; the node wraps it):
          status: committed | stale_revision | idempotent_replay |
                  patch_id_conflict | store_error
          previousRevision / currentRevision / reasonCodes
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            with self._store._connect() as conn:
                # Switch to autocommit so we can issue an explicit BEGIN IMMEDIATE
                # and group the read-check-write into one atomic transaction.
                conn.isolation_level = None

                # --- Phase 1: idempotency / conflict (read-only) ---
                log_row = conn.execute(
                    "SELECT patch_hash, applied_revision FROM card_state_patch_log "
                    "WHERE card_id = ? AND session_id = ? AND patch_id = ?",
                    (card_id, session_id, patch_id),
                ).fetchone()
                if log_row is not None:
                    if log_row["patch_hash"] == patch_hash:
                        # Replay of an already-applied patch. Return the current
                        # persisted state's revision; no write.
                        cur_row = conn.execute(
                            "SELECT revision FROM card_state "
                            "WHERE card_id = ? AND session_id = ?",
                            (card_id, session_id),
                        ).fetchone()
                        cur_rev = cur_row["revision"] if cur_row else log_row["applied_revision"]
                        return {
                            "status": "idempotent_replay",
                            "previousRevision": cur_rev,
                            "currentRevision": cur_rev,
                            "reasonCodes": ["patch_id_already_applied"],
                        }
                    return {
                        "status": "patch_id_conflict",
                        "reasonCodes": ["patch_id_content_mismatch"],
                    }

                # --- Phase 2: open write transaction & re-check under lock ---
                conn.execute("BEGIN IMMEDIATE")

                row = conn.execute(
                    "SELECT revision FROM card_state "
                    "WHERE card_id = ? AND session_id = ?",
                    (card_id, session_id),
                ).fetchone()
                current_revision = row["revision"] if row else None

                if current_revision is None:
                    conn.execute("ROLLBACK")
                    return {
                        "status": "stale_revision",
                        "previousRevision": None,
                        "currentRevision": None,
                        "reasonCodes": ["state_not_found"],
                    }

                if expected_revision != current_revision:
                    conn.execute("ROLLBACK")
                    return {
                        "status": "stale_revision",
                        "previousRevision": current_revision,
                        "currentRevision": current_revision,
                        "reasonCodes": [
                            f"expected_{expected_revision}_actual_{current_revision}"
                        ],
                    }

                # --- Phase 3: apply (revision bump + state write + log) ---
                new_revision = current_revision + 1
                new_state.cardId = card_id
                new_state.sessionId = session_id
                new_state.revision = new_revision

                conn.execute(
                    "UPDATE card_state SET state_json = ?, revision = ?, updated_at = ? "
                    "WHERE card_id = ? AND session_id = ?",
                    (new_state.to_json(), new_revision, now, card_id, session_id),
                )
                conn.execute(
                    "INSERT INTO card_state_patch_log "
                    "(card_id, session_id, patch_id, patch_hash, applied_revision, applied_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (card_id, session_id, patch_id, patch_hash, new_revision, now),
                )
                conn.execute("COMMIT")

                return {
                    "status": "committed",
                    "previousRevision": current_revision,
                    "currentRevision": new_revision,
                    "reasonCodes": [],
                }
        except Exception as exc:  # noqa: BLE001
            # Any unexpected DB error → store_error, store untouched (tx rolled back).
            return {
                "status": "store_error",
                "reasonCodes": [f"exception:{type(exc).__name__}"],
            }
