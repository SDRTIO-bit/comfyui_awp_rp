"""
Long-term memory management.

Long-term memory stores structured records (events, relationships, preferences)
that persist across sessions. Records are organized by namespace for isolation.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.types import MemoryRecord
from ..core.store import SQLiteStore, get_store


class LongTermMemory:
    """Long-term memory manager with namespace isolation."""
    
    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
    
    def write(
        self,
        namespace: str,
        content: str,
        title: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        entity_ids: Optional[list[str]] = None,
        importance: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
        record_id: Optional[str] = None,
    ) -> MemoryRecord:
        """Write a new memory record."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        record = MemoryRecord(
            id=record_id or self._generate_id(),
            namespace=namespace,
            content=content,
            title=title,
            type=type,
            tags=tags or [],
            entity_ids=entity_ids or [],
            importance=importance,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        
        self._store.upsert_memory(namespace, [record])
        return record
    
    def write_batch(
        self,
        namespace: str,
        records: list[dict[str, Any]],
    ) -> list[MemoryRecord]:
        """Write multiple memory records."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        memory_records = []
        for r in records:
            record = MemoryRecord(
                id=r.get("id") or self._generate_id(),
                namespace=namespace,
                content=r["content"],
                title=r.get("title"),
                type=r.get("type"),
                tags=r.get("tags", []),
                entity_ids=r.get("entity_ids", []),
                importance=r.get("importance"),
                created_at=now,
                updated_at=now,
                metadata=r.get("metadata", {}),
            )
            memory_records.append(record)
        
        self._store.upsert_memory(namespace, memory_records)
        return memory_records
    
    def get(self, namespace: str, record_id: str) -> Optional[MemoryRecord]:
        """Get a single memory record."""
        return self._store.get_memory(namespace, record_id)
    
    def query(
        self,
        namespace: str,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
        type_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[MemoryRecord]:
        """Query memory records with filters."""
        return self._store.list_memories(
            namespace=namespace,
            tags_any=tags_any,
            tags_all=tags_all,
            type_filter=type_filter,
            limit=limit,
        )
    
    def delete(self, namespace: str, record_ids: list[str]) -> int:
        """Delete memory records. Returns count deleted."""
        return self._store.delete_memory(namespace, record_ids)
    
    def list_namespaces(self) -> list[str]:
        """List all namespaces with memory records."""
        # This requires a custom query - for now return empty
        # TODO: Add list_namespaces to store
        return []
    
    def _generate_id(self) -> str:
        """Generate a unique record ID."""
        return f"mem_{uuid.uuid4().hex[:16]}"
    
    # ============ Convenience Methods for RP ============
    
    def write_rp_memory(
        self,
        session_id: str,
        kind: str,
        summary: str,
        entity_ids: list[str],
        tags: Optional[list[str]] = None,
        importance: float = 0.5,
        evidence: Optional[str] = None,
    ) -> MemoryRecord:
        """Write an RP-specific memory record.
        
        Args:
            session_id: RP session ID (used as namespace)
            kind: Memory kind (event, relationship-change, state-change, etc.)
            summary: One-sentence summary of what happened
            entity_ids: Entity IDs involved
            tags: Optional tags
            importance: Importance score 0.0-1.0
            evidence: Optional supporting quote
        """
        metadata = {"kind": kind}
        if evidence:
            metadata["evidence"] = evidence
        
        return self.write(
            namespace=session_id,
            content=summary,
            title=f"[{kind}] {summary[:50]}",
            type=kind,
            tags=tags or [kind],
            entity_ids=entity_ids,
            importance=importance,
            metadata=metadata,
        )
    
    def recall_rp_memories(
        self,
        session_id: str,
        limit: int = 10,
        kinds: Optional[list[str]] = None,
    ) -> list[MemoryRecord]:
        """Recall RP memories for a session."""
        return self.query(
            namespace=session_id,
            type_filter=kinds[0] if kinds else None,
            limit=limit,
        )
