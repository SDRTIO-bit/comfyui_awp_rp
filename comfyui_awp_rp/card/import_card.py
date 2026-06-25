"""
Character card import for SillyTavern V3 format.

Parses character cards, extracts worldbook entries, greetings,
and detects blocked features (scripts, variables, etc.).
"""

import hashlib
import json
import base64
import os
import re
import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from ..core.types import CardImportResult, CardManifest, ImportedGreeting, WorldbookEntry
from ..core.store import SQLiteStore, get_store
from .structure import build_card_structure_context, detect_card_structure


# Blocked feature detection patterns
BLOCKED_PATTERNS = {
    "javascript": [r'\bnew\s+Function\s*\(', r'\bFunction\s*\('],
    "eval": [r'\beval\s*\('],
    "ejs_template": [r'<%[\s\S]*?%>'],
    "getvar_executor": [
        r'\{\{\s*getvar\s*:',
        r'\{\{\s*setvar\s*:',
        r'\{\{\s*addvar\s*:',
    ],
    "import_url": [r'\bimport\s*\(', r'\bfetch\s*\('],
    "script_tag": [r'<script[\s>]', r'<iframe[\s>]'],
}

# Variable detection patterns (for MVU)
VARIABLE_PATTERNS = [
    r'\{\{\s*getvar\s*:',
    r'\{\{\s*setvar\s*:',
    r'\{\{var::',
    r'<%[\s\S]*?%>',
    r'"awpVariableCondition"\s*:',
]


@dataclass
class BlockedFeature:
    """A detected blocked feature."""
    code: str
    location: str
    count: int
    evidence: Optional[str] = None


@dataclass
class ParsedCard:
    """Result of parsing a character card."""
    card_id: str
    name: str
    description: Optional[str]
    first_mes: Optional[str]
    alternate_greetings: list[str]
    character_book: Optional[dict[str, Any]]
    extensions: dict[str, Any]
    blocked_features: list[BlockedFeature]
    variables_detected: bool
    raw_data: dict[str, Any]


class SillyTavernV3Parser:
    """Parser for SillyTavern V3 character cards."""
    
    def parse(self, card_json: dict[str, Any]) -> ParsedCard:
        """Parse a SillyTavern V3 character card."""
        # Validate spec
        spec = card_json.get("spec", "")
        if not spec:
            raise ValueError("Missing spec field")
        
        data = card_json.get("data", {})
        if not data:
            raise ValueError("Missing data field")
        
        # Extract basic fields
        name = data.get("name", "Unknown")
        description = data.get("description")
        first_mes = data.get("first_mes")
        alternate_greetings = data.get("alternate_greetings", [])
        character_book = data.get("character_book")
        extensions = data.get("extensions", {})
        
        # Generate card ID from content hash
        card_id = self._generate_card_id(card_json)
        
        # Detect blocked features
        blocked_features = self._detect_blocked_features(card_json)
        
        # Detect variables
        variables_detected = self._detect_variables(card_json)
        
        return ParsedCard(
            card_id=card_id,
            name=name,
            description=description,
            first_mes=first_mes,
            alternate_greetings=alternate_greetings,
            character_book=character_book,
            extensions=extensions,
            blocked_features=blocked_features,
            variables_detected=variables_detected,
            raw_data=card_json,
        )
    
    def _generate_card_id(self, card_json: dict[str, Any]) -> str:
        """Generate a unique card ID from content hash."""
        content = json.dumps(card_json, sort_keys=True, ensure_ascii=False)
        hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"card_{hash_hex}"
    
    def _detect_blocked_features(self, card_json: dict[str, Any]) -> list[BlockedFeature]:
        """Detect blocked features in the card."""
        all_text = self._collect_strings(card_json)
        features: list[BlockedFeature] = []
        
        for code, patterns in BLOCKED_PATTERNS.items():
            count = 0
            evidence = None
            
            for pattern in patterns:
                matches = re.findall(pattern, all_text, re.IGNORECASE)
                if matches:
                    count += len(matches)
                    if evidence is None:
                        evidence = matches[0][:120]
            
            if count > 0:
                features.append(BlockedFeature(
                    code=code,
                    location="card.data",
                    count=count,
                    evidence=evidence,
                ))
        
        return features
    
    def _detect_variables(self, card_json: dict[str, Any]) -> bool:
        """Detect if the card contains variable patterns."""
        all_text = self._collect_strings(card_json)
        
        for pattern in VARIABLE_PATTERNS:
            if re.search(pattern, all_text, re.IGNORECASE):
                return True
        
        return False

    def _collect_strings(self, obj: Any) -> str:
        """Collect all string values from a nested structure."""
        strings: list[str] = []

        def collect(item: Any) -> None:
            if isinstance(item, str):
                strings.append(item)
            elif isinstance(item, dict):
                for v in item.values():
                    collect(v)
            elif isinstance(item, list):
                for item in item:
                    collect(item)

        collect(obj)
        return "\n".join(strings)


def load_card_json_from_file(path: str) -> dict[str, Any]:
    """Load a SillyTavern card from a JSON or PNG file."""
    clean_path = os.path.expanduser(str(path or "").strip().strip('"'))
    if not clean_path:
        raise ValueError("card file path is empty")
    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"card file not found: {clean_path}")

    ext = os.path.splitext(clean_path)[1].lower()
    if ext == ".json":
        with open(clean_path, "r", encoding="utf-8") as f:
            return json.load(f)
    if ext == ".png":
        return _load_card_json_from_png(clean_path)

    raise ValueError("unsupported card file type. Use .json or SillyTavern .png")


def _load_card_json_from_png(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        data = f.read()

    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("file is not a PNG image")

    text_values: list[tuple[str, str]] = []
    offset = len(signature)
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length

        if chunk_type == b"tEXt":
            if b"\x00" in chunk_data:
                key, value = chunk_data.split(b"\x00", 1)
                text_values.append(
                    (
                        key.decode("latin-1", errors="replace"),
                        value.decode("latin-1", errors="replace"),
                    )
                )
        elif chunk_type == b"zTXt":
            parts = chunk_data.split(b"\x00", 2)
            if len(parts) == 3:
                key, compression_method, compressed = parts
                if compression_method == b"\x00":
                    text_values.append(
                        (
                            key.decode("latin-1", errors="replace"),
                            zlib.decompress(compressed).decode("utf-8", errors="replace"),
                        )
                    )
        elif chunk_type == b"iTXt":
            parts = chunk_data.split(b"\x00", 5)
            if len(parts) == 6:
                key, compression_flag, compression_method, _lang, _translated, text = parts
                if compression_flag == b"\x01" and compression_method == b"\x00":
                    value = zlib.decompress(text).decode("utf-8", errors="replace")
                else:
                    value = text.decode("utf-8", errors="replace")
                text_values.append((key.decode("latin-1", errors="replace"), value))

    preferred_keys = {"chara", "ccv3", "card", "character"}
    ordered = sorted(text_values, key=lambda item: 0 if item[0].lower() in preferred_keys else 1)
    for key, value in ordered:
        parsed = _try_parse_card_payload(value)
        if parsed is not None:
            return parsed

    available = ", ".join(key for key, _ in text_values) or "(none)"
    raise ValueError(f"no SillyTavern card metadata found in PNG. text chunks: {available}")


def _try_parse_card_payload(value: str) -> Optional[dict[str, Any]]:
    text = value.strip()
    candidates = [text]

    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
        candidates.insert(0, decoded)
    except Exception:
        pass

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("spec" in parsed or "data" in parsed):
            return parsed
    return None


class CardImporter:
    """Imports character cards into the system."""
    
    def __init__(self, store: Optional[SQLiteStore] = None):
        self._store = store or get_store()
        self._parser = SillyTavernV3Parser()
    
    def import_card(self, card_json: dict[str, Any]) -> CardImportResult:
        """Import a character card."""
        # Parse the card
        parsed = self._parser.parse(card_json)
        
        # Check if already exists
        existing = self._store.load_card(parsed.card_id)
        already_existed = existing is not None
        
        # Extract greetings
        greetings = self._extract_greetings(parsed)
        
        # Extract worldbook entries
        worldbook_entries = self._extract_worldbook(parsed)

        # Detect author-provided structural intent such as phases/events/MVU fields.
        card_structure = detect_card_structure(card_json)
        card_structure_context = build_card_structure_context(card_structure)
        
        # Build manifest
        manifest = CardManifest(
            schema_version=1,
            card_id=parsed.card_id,
            source_filename="imported.json",
            source_size_bytes=len(json.dumps(card_json)),
            source_hash=parsed.card_id,
            imported_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            spec=card_json.get("spec", "chara_card_v3"),
            name=parsed.name,
            description=parsed.description,
            tags=[],
            worldbook_entry_count=len(worldbook_entries),
            alternate_greeting_count=len(parsed.alternate_greetings),
            default_greeting_id=greetings[0].greeting_id if greetings else None,
        )
        
        # Save to store
        self._store.save_card(
            card_id=parsed.card_id,
            manifest={
                "schema_version": manifest.schema_version,
                "card_id": manifest.card_id,
                "name": manifest.name,
                "description": manifest.description,
                "imported_at": manifest.imported_at,
                "worldbook_entry_count": manifest.worldbook_entry_count,
                "default_greeting_id": manifest.default_greeting_id,
                "has_structure": bool(card_structure.get("has_structure")),
            },
            greetings=[
                {
                    "greeting_id": g.greeting_id,
                    "index": g.index,
                    "label": g.label,
                    "content": g.content,
                    "is_default": g.is_default,
                }
                for g in greetings
            ],
            worldbook=[
                {
                    "id": e.id,
                    "content": e.content,
                    "title": e.title,
                    "tags": e.tags,
                    "type": e.type,
                    "priority": e.priority,
                    "metadata": e.metadata,
                }
                for e in worldbook_entries
            ],
            deferred=[],
            report={
                "blocked_features": [
                    {"code": f.code, "count": f.count}
                    for f in parsed.blocked_features
                ],
                "variables_detected": parsed.variables_detected,
                "card_structure": card_structure,
                "card_structure_context": card_structure_context,
            },
        )
        
        return CardImportResult(
            card_id=parsed.card_id,
            already_existed=already_existed,
            manifest=manifest,
            greetings=greetings,
            default_greeting_id=manifest.default_greeting_id,
        )
    
    def _extract_greetings(self, parsed: ParsedCard) -> list[ImportedGreeting]:
        """Extract greetings from parsed card."""
        greetings: list[ImportedGreeting] = []
        
        # First message
        if parsed.first_mes:
            cleaned = self._clean_greeting(parsed.first_mes)
            greetings.append(ImportedGreeting(
                greeting_id="g0",
                index=0,
                label="Default",
                content=cleaned,
                content_hash=hashlib.sha256(cleaned.encode()).hexdigest()[:16],
                is_default=True,
            ))
        
        # Alternate greetings
        for i, alt in enumerate(parsed.alternate_greetings):
            content = alt if isinstance(alt, str) else alt.get("greeting", "")
            if content:
                cleaned = self._clean_greeting(content)
                greetings.append(ImportedGreeting(
                    greeting_id=f"g{i+1}",
                    index=i + 1,
                    label=alt.get("label") if isinstance(alt, dict) else None,
                    content=cleaned,
                    content_hash=hashlib.sha256(cleaned.encode()).hexdigest()[:16],
                    is_default=False,
                ))
        
        return greetings
    
    def _extract_worldbook(self, parsed: ParsedCard) -> list[WorldbookEntry]:
        """Extract worldbook entries from parsed card."""
        entries: list[WorldbookEntry] = []
        
        if not parsed.character_book:
            return entries
        
        book_entries = parsed.character_book.get("entries", [])
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        for i, be in enumerate(book_entries):
            content = be.get("content", "")
            if not content:
                continue
            
            # Check if entry should be blocked
            if self._should_block_entry(be):
                continue
            
            # Extract keys as tags
            keys = be.get("keys", [])
            if isinstance(keys, str):
                keys = [keys]
            
            entry = WorldbookEntry(
                id=f"wb_{be.get('uid', i)}",
                content=content,
                title=be.get("comment") or be.get("name"),
                type="worldbook",
                tags=keys,
                priority=be.get("priority", 0),
                created_at=now,
                updated_at=now,
                metadata={
                    "source_uid": be.get("uid"),
                    "constant": be.get("constant", False),
                    "selective": be.get("selective", False),
                    "enabled": not be.get("disable", False),
                    "keywords": keys,
                },
            )
            entries.append(entry)
        
        return entries
    
    def _should_block_entry(self, entry: dict[str, Any]) -> bool:
        """Check if an entry should be blocked."""
        content = entry.get("content", "")
        
        # Check for script patterns
        for patterns in BLOCKED_PATTERNS.values():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    return True
        
        return False
    
    def _clean_greeting(self, content: str) -> str:
        """Clean a greeting by removing blocked patterns."""
        cleaned = content
        
        # Remove status bar placeholders
        cleaned = re.sub(r'\{\{\s*status_bar\s*\}\}', '', cleaned, flags=re.IGNORECASE)
        
        # Remove variable update tags
        cleaned = re.sub(r'\{\{\s*setvar\s*:[^}]*\}\}', '', cleaned, flags=re.IGNORECASE)
        
        # Remove EJS templates
        cleaned = re.sub(r'<%[\s\S]*?%>', '', cleaned)
        
        # Remove script tags
        cleaned = re.sub(r'<script[\s\S]*?</script>', '', cleaned, flags=re.IGNORECASE)
        
        # Normalize whitespace
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        
        return cleaned
    
    def list_cards(self) -> list[dict[str, Any]]:
        """List all imported cards."""
        return self._store.list_cards()
    
    def get_card(self, card_id: str) -> Optional[dict[str, Any]]:
        """Get a card by ID."""
        return self._store.load_card(card_id)
    
    def delete_card(self, card_id: str) -> bool:
        """Delete a card."""
        return self._store.delete_card(card_id)
