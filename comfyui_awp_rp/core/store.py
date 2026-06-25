"""
SQLite storage backend for AWP RP Plugin.

Provides persistent storage for:
- Agent sessions (short-term memory)
- Memory records (long-term memory)
- Worldbook entries
- Variable state (MVU)
- Character cards
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from .types import (
    AgentSessionContext,
    AgentSessionKey,
    AgentTurn,
    LlmTokenUsage,
    MemoryRecord,
    VariableStateSnapshot,
    WorldbookEntry,
    WorldbookSnapshot,
)


class SQLiteStore:
    """SQLite-based persistent storage."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database tables."""
        with self._connect() as conn:
            conn.executescript("""
                -- Agent sessions (short-term memory)
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_key TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workflow_instance_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    agent_node_id TEXT NOT NULL,
                    branch_id TEXT,
                    turns_json TEXT NOT NULL DEFAULT '[]',
                    summary TEXT,
                    estimated_tokens INTEGER DEFAULT 0,
                    truncated INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                
                -- Memory records (long-term memory)
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    content TEXT NOT NULL,
                    title TEXT,
                    type TEXT,
                    tags_json TEXT DEFAULT '[]',
                    entity_ids_json TEXT DEFAULT '[]',
                    importance REAL,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory_records(namespace);
                
                -- Worldbook entries
                CREATE TABLE IF NOT EXISTS worldbook_entries (
                    id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    resource_ref TEXT NOT NULL,
                    content TEXT NOT NULL,
                    title TEXT,
                    type TEXT,
                    tags_json TEXT DEFAULT '[]',
                    entity_ids_json TEXT DEFAULT '[]',
                    priority REAL,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, resource_ref, id)
                );
                CREATE INDEX IF NOT EXISTS idx_worldbook_scope ON worldbook_entries(scope_key, resource_ref);
                
                -- Worldbook snapshots (version tracking)
                CREATE TABLE IF NOT EXISTS worldbook_snapshots (
                    scope_key TEXT NOT NULL,
                    resource_ref TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    entry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, resource_ref)
                );
                
                -- Variable state (MVU)
                CREATE TABLE IF NOT EXISTS variable_state (
                    card_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    slot TEXT NOT NULL DEFAULT 'default',
                    revision INTEGER DEFAULT 0,
                    values_json TEXT NOT NULL DEFAULT '{}',
                    state_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (card_id, session_id, slot)
                );
                
                -- Character cards
                CREATE TABLE IF NOT EXISTS character_cards (
                    card_id TEXT PRIMARY KEY,
                    manifest_json TEXT NOT NULL,
                    greetings_json TEXT NOT NULL DEFAULT '[]',
                    worldbook_json TEXT NOT NULL DEFAULT '[]',
                    deferred_worldbook_json TEXT NOT NULL DEFAULT '[]',
                    import_report_json TEXT NOT NULL DEFAULT '{}',
                    imported_at TEXT NOT NULL
                );
                
                -- Provider configurations
                CREATE TABLE IF NOT EXISTS providers (
                    provider_id TEXT PRIMARY KEY,
                    api_key TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    default_model TEXT NOT NULL,
                    models_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                
                -- Agent profiles (system prompts)
                CREATE TABLE IF NOT EXISTS agent_profiles (
                    profile_id TEXT PRIMARY KEY,
                    label_zh TEXT NOT NULL,
                    label_en TEXT NOT NULL,
                    description_zh TEXT NOT NULL,
                    description_en TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    model_config_json TEXT NOT NULL DEFAULT '{}',
                    locked_fields_json TEXT DEFAULT '[]',
                    runtime_role TEXT,
                    quality_tier TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                
                -- Presets
                CREATE TABLE IF NOT EXISTS presets (
                    preset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                
                -- Skills
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT PRIMARY KEY,
                    label_zh TEXT NOT NULL,
                    label_en TEXT NOT NULL,
                    content_zh TEXT NOT NULL,
                    content_en TEXT NOT NULL,
                    category TEXT,
                    tags_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Projects (RP session or novel project)
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'rp',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );

                -- Project snapshots (saved per turn or chapter)
                CREATE TABLE IF NOT EXISTS project_snapshots (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    snapshot_type TEXT NOT NULL DEFAULT 'turn',
                    narrative TEXT,
                    context_json TEXT,
                    quality_json TEXT,
                    memory_candidates_json TEXT,
                    worldbook_changes_json TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_project ON project_snapshots(project_id, created_at);

                -- Outlines (novel structure: volumes, chapters, plot points, foreshadowing)
                CREATE TABLE IF NOT EXISTS outlines (
                    project_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_type TEXT NOT NULL DEFAULT 'chapter',
                    title TEXT,
                    content TEXT,
                    parent_id TEXT,
                    order_index INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'planned',
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, node_id)
                );
                CREATE INDEX IF NOT EXISTS idx_outlines_project ON outlines(project_id, parent_id, order_index);
            """)
    
    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with automatic commit/rollback."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _now(self) -> str:
        """Get current ISO timestamp."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # ============ Agent Session Methods ============
    
    def _session_key_str(self, key: AgentSessionKey) -> str:
        """Convert session key to string."""
        return f"{key.tenant_id}:{key.workflow_instance_id}:{key.conversation_id}:{key.agent_node_id}:{key.branch_id or ''}"
    
    def load_session(self, key: AgentSessionKey) -> Optional[AgentSessionContext]:
        """Load an agent session."""
        key_str = self._session_key_str(key)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE session_key = ?",
                (key_str,)
            ).fetchone()
            
            if not row:
                return None
            
            turns_data = json.loads(row["turns_json"])
            turns = [
                AgentTurn(
                    turn_index=t["turn_index"],
                    input=t["input"],
                    assistant_output=t["assistant_output"],
                    model_config=t.get("model_config", {}),
                    token_usage=LlmTokenUsage(
                        input=t.get("token_usage", {}).get("input", 0),
                        output=t.get("token_usage", {}).get("output", 0),
                    ),
                    created_at=t.get("created_at", ""),
                )
                for t in turns_data
            ]
            
            return AgentSessionContext(
                session_key=key,
                turns=turns,
                summary=row["summary"],
                estimated_tokens=row["estimated_tokens"],
                truncated=bool(row["truncated"]),
            )
    
    def save_session(self, context: AgentSessionContext) -> None:
        """Save an agent session."""
        key = context.session_key
        key_str = self._session_key_str(key)
        now = self._now()
        
        turns_data = [
            {
                "turn_index": t.turn_index,
                "input": t.input,
                "assistant_output": t.assistant_output,
                "model_config": t.model_config,
                "token_usage": {"input": t.token_usage.input, "output": t.token_usage.output},
                "created_at": t.created_at,
            }
            for t in context.turns
        ]
        
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO agent_sessions
                (session_key, tenant_id, workflow_instance_id, conversation_id, 
                 agent_node_id, branch_id, turns_json, summary, estimated_tokens, 
                 truncated, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key_str,
                key.tenant_id,
                key.workflow_instance_id,
                key.conversation_id,
                key.agent_node_id,
                key.branch_id,
                json.dumps(turns_data),
                context.summary,
                context.estimated_tokens,
                int(context.truncated),
                now,
                now,
            ))
    
    def delete_session(self, key: AgentSessionKey) -> None:
        """Delete an agent session."""
        key_str = self._session_key_str(key)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM agent_sessions WHERE session_key = ?",
                (key_str,)
            )
    
    def list_sessions(self) -> list[dict]:
        """List all agent sessions (summaries only)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_key, conversation_id, turns_json, summary, updated_at FROM agent_sessions ORDER BY updated_at DESC"
            ).fetchall()
            result = []
            for row in rows:
                turns = json.loads(row["turns_json"]) if row["turns_json"] else []
                result.append({
                    "session_key": row["session_key"],
                    "conversation_id": row["conversation_id"],
                    "turn_count": len(turns),
                    "summary": row["summary"],
                    "updated_at": row["updated_at"],
                })
            return result
    
    # ============ Memory Record Methods ============
    
    def upsert_memory(self, namespace: str, records: list[MemoryRecord]) -> int:
        """Upsert memory records. Returns count of records written."""
        now = self._now()
        count = 0
        
        with self._connect() as conn:
            for record in records:
                record.created_at = record.created_at or now
                record.updated_at = now
                
                conn.execute("""
                    INSERT OR REPLACE INTO memory_records
                    (id, namespace, content, title, type, tags_json, entity_ids_json,
                     importance, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.id,
                    namespace,
                    record.content,
                    record.title,
                    record.type,
                    json.dumps(record.tags),
                    json.dumps(record.entity_ids),
                    record.importance,
                    json.dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ))
                count += 1
        
        return count
    
    def get_memory(self, namespace: str, record_id: str) -> Optional[MemoryRecord]:
        """Get a single memory record."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_records WHERE namespace = ? AND id = ?",
                (namespace, record_id)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_memory_record(row)
    
    def list_memories(
        self,
        namespace: str,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
        type_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[MemoryRecord]:
        """List memory records with optional filters."""
        query = "SELECT * FROM memory_records WHERE namespace = ?"
        params: list[Any] = [namespace]
        
        if tags_any:
            # Match any of the tags
            tag_conditions = " OR ".join(["tags_json LIKE ?"] * len(tags_any))
            query += f" AND ({tag_conditions})"
            params.extend([f'%"{tag}"%' for tag in tags_any])
        
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_record(row) for row in rows]
    
    def delete_memory(self, namespace: str, record_ids: list[str]) -> int:
        """Delete memory records. Returns count deleted."""
        if not record_ids:
            return 0
        
        placeholders = ",".join(["?"] * len(record_ids))
        with self._connect() as conn:
            result = conn.execute(
                f"DELETE FROM memory_records WHERE namespace = ? AND id IN ({placeholders})",
                [namespace] + record_ids
            )
            return result.rowcount
    
    def _row_to_memory_record(self, row: sqlite3.Row) -> MemoryRecord:
        """Convert a database row to a MemoryRecord."""
        return MemoryRecord(
            id=row["id"],
            namespace=row["namespace"],
            content=row["content"],
            title=row["title"],
            type=row["type"],
            tags=json.loads(row["tags_json"]),
            entity_ids=json.loads(row["entity_ids_json"]),
            importance=row["importance"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata_json"]),
        )
    
    # ============ Worldbook Methods ============
    
    def load_worldbook(self, scope_key: str, resource_ref: str) -> WorldbookSnapshot:
        """Load a worldbook snapshot."""
        with self._connect() as conn:
            # Get version info
            version_row = conn.execute(
                "SELECT version FROM worldbook_snapshots WHERE scope_key = ? AND resource_ref = ?",
                (scope_key, resource_ref)
            ).fetchone()
            
            version = version_row["version"] if version_row else 0
            
            # Get entries
            rows = conn.execute(
                "SELECT * FROM worldbook_entries WHERE scope_key = ? AND resource_ref = ?",
                (scope_key, resource_ref)
            ).fetchall()
            
            entries = [self._row_to_worldbook_entry(row) for row in rows]
            
            return WorldbookSnapshot(
                resource_ref=resource_ref,
                version=version,
                entries=entries,
                total=len(entries),
            )
    
    def save_worldbook(self, scope_key: str, resource_ref: str, snapshot: WorldbookSnapshot) -> None:
        """Save a worldbook snapshot."""
        now = self._now()
        
        with self._connect() as conn:
            # Delete existing entries
            conn.execute(
                "DELETE FROM worldbook_entries WHERE scope_key = ? AND resource_ref = ?",
                (scope_key, resource_ref)
            )
            
            # Insert new entries
            for entry in snapshot.entries:
                entry.created_at = entry.created_at or now
                entry.updated_at = now
                
                conn.execute("""
                    INSERT INTO worldbook_entries
                    (id, scope_key, resource_ref, content, title, type, tags_json,
                     entity_ids_json, priority, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.id,
                    scope_key,
                    resource_ref,
                    entry.content,
                    entry.title,
                    entry.type,
                    json.dumps(entry.tags),
                    json.dumps(entry.entity_ids),
                    entry.priority,
                    json.dumps(entry.metadata),
                    entry.created_at,
                    entry.updated_at,
                ))
            
            # Update version
            conn.execute("""
                INSERT OR REPLACE INTO worldbook_snapshots
                (scope_key, resource_ref, version, entry_count, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                scope_key,
                resource_ref,
                snapshot.version,
                len(snapshot.entries),
                now,
            ))
    
    def _row_to_worldbook_entry(self, row: sqlite3.Row) -> WorldbookEntry:
        """Convert a database row to a WorldbookEntry."""
        return WorldbookEntry(
            id=row["id"],
            content=row["content"],
            title=row["title"],
            type=row["type"],
            tags=json.loads(row["tags_json"]),
            entity_ids=json.loads(row["entity_ids_json"]),
            priority=row["priority"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata_json"]),
        )
    
    # ============ Variable State Methods (MVU) ============
    
    def load_variable_state(
        self,
        card_id: str,
        session_id: str,
        slot: str = "default",
    ) -> Optional[VariableStateSnapshot]:
        """Load variable state for a card session."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM variable_state WHERE card_id = ? AND session_id = ? AND slot = ?",
                (card_id, session_id, slot)
            ).fetchone()
            
            if not row:
                return None
            
            return VariableStateSnapshot(
                card_id=row["card_id"],
                session_id=row["session_id"],
                slot=row["slot"],
                revision=row["revision"],
                values=json.loads(row["values_json"]),
                state_hash=row["state_hash"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    
    def save_variable_state(self, snapshot: VariableStateSnapshot) -> None:
        """Save variable state."""
        now = self._now()
        snapshot.updated_at = now
        
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO variable_state
                (card_id, session_id, slot, revision, values_json, state_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.card_id,
                snapshot.session_id,
                snapshot.slot,
                snapshot.revision,
                json.dumps(snapshot.values),
                snapshot.state_hash,
                snapshot.created_at or now,
                snapshot.updated_at,
            ))
    
    # ============ Character Card Methods ============
    
    def save_card(self, card_id: str, manifest: dict, greetings: list, worldbook: list, 
                  deferred: list, report: dict) -> None:
        """Save a character card."""
        now = self._now()
        
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO character_cards
                (card_id, manifest_json, greetings_json, worldbook_json, 
                 deferred_worldbook_json, import_report_json, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                card_id,
                json.dumps(manifest),
                json.dumps(greetings),
                json.dumps(worldbook),
                json.dumps(deferred),
                json.dumps(report),
                now,
            ))
    
    def load_card(self, card_id: str) -> Optional[dict]:
        """Load a character card."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM character_cards WHERE card_id = ?",
                (card_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return {
                "card_id": row["card_id"],
                "manifest": json.loads(row["manifest_json"]),
                "greetings": json.loads(row["greetings_json"]),
                "worldbook": json.loads(row["worldbook_json"]),
                "deferred_worldbook": json.loads(row["deferred_worldbook_json"]),
                "import_report": json.loads(row["import_report_json"]),
                "imported_at": row["imported_at"],
            }
    
    def list_cards(self) -> list[dict]:
        """List all character cards (manifests only)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT card_id, manifest_json, imported_at FROM character_cards ORDER BY imported_at DESC"
            ).fetchall()
            
            return [
                {
                    "card_id": row["card_id"],
                    "manifest": json.loads(row["manifest_json"]),
                    "imported_at": row["imported_at"],
                }
                for row in rows
            ]
    
    def delete_card(self, card_id: str) -> bool:
        """Delete a character card."""
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM character_cards WHERE card_id = ?",
                (card_id,)
            )
            return result.rowcount > 0

    # ============ Project Methods ============

    def save_project(
        self,
        project_id: str,
        name: str,
        project_type: str = "rp",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Create or update a project."""
        now = self._now()
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO projects
                (project_id, name, type, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                name,
                project_type,
                now,
                now,
                json.dumps(metadata or {}, ensure_ascii=False),
            ))

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        """Get a project by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "project_id": row["project_id"],
                "name": row["name"],
                "type": row["type"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
            return [
                {
                    "project_id": row["project_id"],
                    "name": row["name"],
                    "type": row["type"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                }
                for row in rows
            ]

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and its snapshots."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM project_snapshots WHERE project_id = ?",
                (project_id,)
            )
            result = conn.execute(
                "DELETE FROM projects WHERE project_id = ?",
                (project_id,)
            )
            return result.rowcount > 0

    def save_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
        snapshot_type: str = "turn",
        narrative: str = "",
        context: Optional[dict[str, Any]] = None,
        quality: Optional[dict[str, Any]] = None,
        memory_candidates: Optional[list] = None,
        worldbook_changes: Optional[list] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Save a project snapshot."""
        now = self._now()
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO project_snapshots
                (id, project_id, snapshot_type, narrative, context_json,
                 quality_json, memory_candidates_json, worldbook_changes_json,
                 metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id,
                project_id,
                snapshot_type,
                narrative,
                json.dumps(context or {}, ensure_ascii=False),
                json.dumps(quality or {}, ensure_ascii=False),
                json.dumps(memory_candidates or [], ensure_ascii=False),
                json.dumps(worldbook_changes or [], ensure_ascii=False),
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
            ))
            # Update project timestamp
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (now, project_id)
            )

    def get_snapshot(self, project_id: str, snapshot_id: str) -> Optional[dict[str, Any]]:
        """Get a specific snapshot."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_snapshots WHERE project_id = ? AND id = ?",
                (project_id, snapshot_id)
            ).fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    def list_snapshots(self, project_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """List snapshots for a project, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_snapshots WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
            return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "snapshot_type": row["snapshot_type"],
            "narrative": row["narrative"],
            "context": json.loads(row["context_json"] or "{}"),
            "quality": json.loads(row["quality_json"] or "{}"),
            "memory_candidates": json.loads(row["memory_candidates_json"] or "[]"),
            "worldbook_changes": json.loads(row["worldbook_changes_json"] or "[]"),
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        }

    # ============ Outline Methods ============

    def save_outline_node(
        self,
        project_id: str,
        node_id: str,
        node_type: str = "chapter",
        title: str = "",
        content: str = "",
        parent_id: str = "",
        order_index: int = 0,
        status: str = "planned",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Create or update an outline node."""
        now = self._now()
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO outlines
                (project_id, node_id, node_type, title, content, parent_id,
                 order_index, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                node_id,
                node_type,
                title,
                content,
                parent_id,
                order_index,
                status,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                now,
            ))

    def get_outline_node(self, project_id: str, node_id: str) -> Optional[dict[str, Any]]:
        """Get a single outline node."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM outlines WHERE project_id = ? AND node_id = ?",
                (project_id, node_id)
            ).fetchone()
            if not row:
                return None
            return self._row_to_outline(row)

    def list_outline_nodes(
        self,
        project_id: str,
        parent_id: Optional[str] = None,
        node_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List outline nodes, optionally filtered by parent or type."""
        query = "SELECT * FROM outlines WHERE project_id = ?"
        params: list[Any] = [project_id]
        if parent_id is not None:
            query += " AND parent_id = ?"
            params.append(parent_id)
        if node_type:
            query += " AND node_type = ?"
            params.append(node_type)
        query += " ORDER BY order_index ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_outline(row) for row in rows]

    def delete_outline_node(self, project_id: str, node_id: str) -> bool:
        """Delete an outline node."""
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM outlines WHERE project_id = ? AND node_id = ?",
                (project_id, node_id)
            )
            return result.rowcount > 0

    def _row_to_outline(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "project_id": row["project_id"],
            "node_id": row["node_id"],
            "node_type": row["node_type"],
            "title": row["title"],
            "content": row["content"],
            "parent_id": row["parent_id"],
            "order_index": row["order_index"],
            "status": row["status"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


# Global store instance
_store: Optional[SQLiteStore] = None


def get_store() -> SQLiteStore:
    """Get the global store instance."""
    global _store
    if _store is None:
        from .config import get_config
        config = get_config()
        db_path = os.path.join(config.data_dir, "awp.db")
        _store = SQLiteStore(db_path)
    return _store


def set_store(store: SQLiteStore) -> None:
    """Set the global store instance."""
    global _store
    _store = store
