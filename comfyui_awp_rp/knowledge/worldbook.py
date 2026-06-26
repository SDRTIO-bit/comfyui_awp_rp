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


def filter_st_worldbook_entries(
    entries: list[dict[str, Any]],
    user_input: str,
    history_text: str = "",
) -> list[dict[str, Any]]:
    """Filter SillyTavern-style worldbook entries by activation rules.

    Rules (matching SillyTavern behaviour):
      - ``disable: true`` or ``enabled: false`` → excluded
      - ``constant: true`` → always included
      - Has ``keys`` (non-empty) → included only when user_input or
        history_text contains at least one key (case-insensitive)
      - No keys AND not constant → excluded (orphan entry)

    Returns filtered entries with original metadata preserved.
    """
    search_text = (user_input + " " + history_text).lower()
    filtered: list[dict[str, Any]] = []

    for entry in entries:
        # Honour disable flag
        if entry.get("disable", False):
            continue
        if entry.get("enabled") is False:
            continue

        # Per-entry metadata may override top-level flags
        meta = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        if meta.get("enabled") is False:
            continue

        is_constant = bool(
            entry.get("constant")
            or meta.get("constant")
        )

        if is_constant:
            filtered.append(entry)
            continue

        # Keyword-triggered: check keys against input + history
        keys = entry.get("keys") or meta.get("keywords") or entry.get("tags") or []
        if isinstance(keys, str):
            keys = [keys]

        # Flatten nested key lists
        flat_keys: list[str] = []
        for k in keys:
            if isinstance(k, list):
                flat_keys.extend(str(x).lower() for x in k)
            else:
                flat_keys.append(str(k).lower())

        if flat_keys and any(k in search_text for k in flat_keys):
            filtered.append(entry)

    return filtered


def _estimate_tokens(text: str) -> int:
    """Stable, dependency-free token estimate (≈ len//4)."""
    return max(1, (len(text) + 3) // 4) if text else 0


def _entry_token_cost(entry: dict[str, Any]) -> int:
    content = str(entry.get("content", "")) + str(entry.get("comment") or entry.get("title") or "")
    return _estimate_tokens(content)


def apply_worldbook_budget(
    entries: list[dict[str, Any]],
    budget_tokens: int,
    *,
    keep_core: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply a token budget to worldbook entries.

    Core/constant entries are kept first (up to budget); remaining budget is
    spent on triggered entries by descending priority. Returns
    ``(included, report)`` where ``report`` records considered/included/dropped
    counts, token estimates, and per-entry drop reasons.

    This stops constant entries from accumulating unbounded (the 64k explosion
    root cause). It never mutates the input entries.
    """
    considered = list(entries)
    # Sort: constant first, then by priority desc, stable.
    def _sort_key(e: dict[str, Any]) -> tuple[int, float]:
        is_const = bool(e.get("constant") or (e.get("metadata") or {}).get("constant"))
        priority = float(e.get("priority", 0) or 0)
        return (0 if is_const else 1, -priority)

    ordered = sorted(considered, key=_sort_key)

    included: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    used_tokens = 0
    core_tokens = 0
    retrieved_tokens = 0

    for e in ordered:
        is_const = bool(e.get("constant") or (e.get("metadata") or {}).get("constant"))
        cost = _entry_token_cost(e)
        if keep_core and is_const:
            # Core entries are always eligible but still count against budget.
            if used_tokens + cost <= budget_tokens or not included:
                included.append(e)
                used_tokens += cost
                core_tokens += cost
            else:
                dropped.append({"comment": e.get("comment") or e.get("title"), "reason": "budget-core-overflow"})
        else:
            if used_tokens + cost <= budget_tokens:
                included.append(e)
                used_tokens += cost
                retrieved_tokens += cost
            else:
                dropped.append({"comment": e.get("comment") or e.get("title"), "reason": "budget-exceeded"})

    report = {
        "worldbook_entries_considered": len(considered),
        "worldbook_entries_included": len(included),
        "worldbook_entries_dropped": len(dropped),
        "core_worldbook_token_estimate": core_tokens,
        "retrieved_worldbook_token_estimate": retrieved_tokens,
        "total_token_estimate": used_tokens,
        "budget_tokens": budget_tokens,
        "drop_reasons": dropped,
    }
    return included, report


def build_filtered_worldbook_text(
    entries: list[dict[str, Any]],
    user_input: str,
    history_text: str = "",
    max_entries: int = 40,
    budget_tokens: int = 8000,
) -> str:
    """Build a filtered worldbook context string.

    Returns a formatted string suitable for injection into the system prompt.
    Only includes entries that pass :func:`filter_st_worldbook_entries`.

    A token ``budget_tokens`` cap (legacy-fallback default 8000) is enforced via
    :func:`apply_worldbook_budget` so constant entries can no longer accumulate
    to 64k+. Set ``budget_tokens=0`` to disable the cap (not recommended).
    """
    filtered = filter_st_worldbook_entries(entries, user_input, history_text)

    if not filtered:
        return ""

    # Sort: constant first, then by priority desc
    def _sort_key(e: dict[str, Any]) -> tuple[int, float]:
        is_const = bool(e.get("constant") or (e.get("metadata") or {}).get("constant"))
        priority = float(e.get("priority", 0) or 0)
        return (0 if is_const else 1, -priority)

    filtered.sort(key=_sort_key)
    filtered = filtered[:max_entries]

    if budget_tokens and budget_tokens > 0:
        filtered, _report = apply_worldbook_budget(filtered, budget_tokens)

    parts: list[str] = ["## World & Character Lore"]
    for entry in filtered:
        comment = entry.get("comment") or entry.get("title") or ""
        content = entry.get("content", "")
        if not content.strip():
            continue
        is_const = bool(entry.get("constant") or (entry.get("metadata") or {}).get("constant"))
        keys = entry.get("keys") or entry.get("tags") or []
        if isinstance(keys, str):
            keys = [keys]
        tag = "◆ 常开" if is_const else ("◇ 匹配: " + ", ".join(str(k) for k in keys[:3]))
        header = f"### {comment} ({tag})" if comment else f"### Entry ({tag})"
        parts.append(f"{header}\n{content}")

    return "\n\n".join(parts)
