"""
Dynamic Worldbook management.

Worldbook is a stateful, queryable, writable knowledge base with versioning
and idempotent operations. Entries can be added, updated, and queried.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.types import WorldbookEntry, WorldbookSnapshot
from ..core.store import SQLiteStore, get_store


class Worldbook:
    """A single worldbook instance."""
    
    def __init__(
        self,
        scope_key: str,
        resource_ref: str,
        store: Optional[SQLiteStore] = None,
    ):
        self.scope_key = scope_key
        self.resource_ref = resource_ref
        self._store = store or get_store()
        self._snapshot: Optional[WorldbookSnapshot] = None
    
    def load(self) -> WorldbookSnapshot:
        """Load the worldbook snapshot."""
        self._snapshot = self._store.load_worldbook(self.scope_key, self.resource_ref)
        return self._snapshot
    
    def save(self) -> None:
        """Save the worldbook snapshot."""
        if self._snapshot:
            self._store.save_worldbook(self.scope_key, self.resource_ref, self._snapshot)
    
    def get_entries(self) -> list[WorldbookEntry]:
        """Get all entries in the worldbook."""
        if self._snapshot is None:
            self.load()
        return self._snapshot.entries if self._snapshot else []
    
    def get_entry(self, entry_id: str) -> Optional[WorldbookEntry]:
        """Get a single entry by ID."""
        for entry in self.get_entries():
            if entry.id == entry_id:
                return entry
        return None
    
    def add_entry(
        self,
        content: str,
        entry_id: Optional[str] = None,
        title: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        entity_ids: Optional[list[str]] = None,
        priority: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> WorldbookEntry:
        """Add a new entry to the worldbook."""
        if self._snapshot is None:
            self.load()
        
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        entry = WorldbookEntry(
            id=entry_id or self._generate_id(),
            content=content,
            title=title,
            type=type,
            tags=tags or [],
            entity_ids=entity_ids or [],
            priority=priority,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        
        self._snapshot.entries.append(entry)
        self._snapshot.total = len(self._snapshot.entries)
        self._snapshot.version += 1
        
        self.save()
        return entry
    
    def update_entry(
        self,
        entry_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
        priority: Optional[float] = None,
    ) -> Optional[WorldbookEntry]:
        """Update an existing entry."""
        if self._snapshot is None:
            self.load()
        
        for entry in self._snapshot.entries:
            if entry.id == entry_id:
                if content is not None:
                    entry.content = content
                if title is not None:
                    entry.title = title
                if tags is not None:
                    entry.tags = tags
                if priority is not None:
                    entry.priority = priority
                entry.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                
                self._snapshot.version += 1
                self.save()
                return entry
        
        return None
    
    def delete_entry(self, entry_id: str) -> bool:
        """Delete an entry from the worldbook."""
        if self._snapshot is None:
            self.load()
        
        initial_count = len(self._snapshot.entries)
        self._snapshot.entries = [
            e for e in self._snapshot.entries if e.id != entry_id
        ]
        
        if len(self._snapshot.entries) < initial_count:
            self._snapshot.total = len(self._snapshot.entries)
            self._snapshot.version += 1
            self.save()
            return True
        
        return False
    
    def query(
        self,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
        type_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[WorldbookEntry]:
        """Query entries with filters."""
        entries = self.get_entries()
        result = []
        
        for entry in entries:
            # Tags any filter
            if tags_any:
                if not any(tag in entry.tags for tag in tags_any):
                    continue
            
            # Tags all filter
            if tags_all:
                if not all(tag in entry.tags for tag in tags_all):
                    continue
            
            # Type filter
            if type_filter and entry.type != type_filter:
                continue
            
            result.append(entry)
        
        if limit:
            result = result[:limit]
        
        return result
    
    def _generate_id(self) -> str:
        """Generate a unique entry ID."""
        return f"wb_{uuid.uuid4().hex[:16]}"


class WorldbookManager:
    """High-level manager for worldbooks."""
    
    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
    
    def get_worldbook(
        self,
        session_id: str,
        resource_ref: str,
    ) -> Worldbook:
        """Get a worldbook for a session."""
        scope_key = f"session:{session_id}:{resource_ref}"
        return Worldbook(scope_key, resource_ref, self._store)
    
    def create_worldbook(
        self,
        session_id: str,
        resource_ref: str,
        entries: Optional[list[dict[str, Any]]] = None,
    ) -> Worldbook:
        """Create a new worldbook with optional initial entries."""
        scope_key = f"session:{session_id}:{resource_ref}"
        worldbook = Worldbook(scope_key, resource_ref, self._store)
        
        # Initialize empty snapshot
        snapshot = WorldbookSnapshot(
            resource_ref=resource_ref,
            version=1,
            entries=[],
            total=0,
        )
        
        # Add initial entries
        if entries:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            for e in entries:
                entry = WorldbookEntry(
                    id=e.get("id") or f"wb_{uuid.uuid4().hex[:16]}",
                    content=e["content"],
                    title=e.get("title"),
                    type=e.get("type"),
                    tags=e.get("tags", []),
                    entity_ids=e.get("entity_ids", []),
                    priority=e.get("priority"),
                    created_at=now,
                    updated_at=now,
                    metadata=e.get("metadata", {}),
                )
                snapshot.entries.append(entry)
            snapshot.total = len(snapshot.entries)
        
        self._store.save_worldbook(scope_key, resource_ref, snapshot)
        return worldbook
    
    def seed_from_card(
        self,
        session_id: str,
        resource_ref: str,
        card_entries: list[dict[str, Any]],
    ) -> Worldbook:
        """Seed a worldbook from character card entries."""
        return self.create_worldbook(session_id, resource_ref, card_entries)
