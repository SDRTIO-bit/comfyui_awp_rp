"""Retrieval tools — BM25/keyword/hybrid document search."""

from __future__ import annotations

import json
from typing import Any

from ...core.types import RetrievalDocument
from ...retrieval.scorer import RetrievalConfig, RetrievalScorer, RetrievalFilters
from ..registry import ToolRegistry, ToolDefinition


def _retrieval_search(args: dict[str, Any]) -> str:
    """Search documents using BM25/keyword/hybrid retrieval."""
    query = args.get("query", "")
    documents_json = args.get("documents_json", "[]")
    strategy = args.get("strategy", "bm25")
    limit = args.get("limit", 8)
    min_score = args.get("min_score", 0.01)

    if not query:
        return "Error: query is required"

    try:
        docs_data = json.loads(documents_json) if documents_json.strip() else []
    except json.JSONDecodeError as e:
        return f"Error parsing documents JSON: {e}"

    documents = [
        RetrievalDocument(
            id=d.get("id", ""),
            content=d.get("content", ""),
            title=d.get("title"),
            type=d.get("type"),
            tags=d.get("tags", []),
            entity_ids=d.get("entity_ids", []),
            priority=d.get("priority"),
        )
        for d in docs_data if isinstance(d, dict)
    ]

    if not documents:
        return "No documents to search"

    config = RetrievalConfig(strategy=strategy, limit=limit, min_score=min_score)
    scorer = RetrievalScorer(config)
    result = scorer.retrieve(query, documents)

    return json.dumps([
        {
            "rank": hit.rank,
            "score": hit.score,
            "id": hit.entry.id,
            "title": hit.entry.title,
            "content": hit.entry.content,
            "matched_terms": hit.matched_terms,
        }
        for hit in result.hits
    ], ensure_ascii=False, indent=2)


def register_retrieval_tools(registry: ToolRegistry) -> None:
    """Register retrieval tools."""
    registry.register(ToolDefinition(
        name="retrieval_search",
        description="Search documents using BM25, keyword, or hybrid retrieval. Use this to find relevant content from a set of documents (e.g. worldbook entries, memory records, chapter summaries).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "documents_json": {
                    "type": "string",
                    "description": "JSON array of documents to search. Each document: {id, content, title, tags, type, priority}.",
                },
                "strategy": {
                    "type": "string",
                    "enum": ["keyword", "bm25", "hybrid"],
                    "description": "Retrieval strategy.",
                    "default": "bm25",
                },
                "limit": {"type": "integer", "description": "Max results.", "default": 8},
                "min_score": {"type": "number", "description": "Minimum score threshold.", "default": 0.01},
            },
            "required": ["query", "documents_json"],
        },
        execute_fn=_retrieval_search,
        required_permissions=["retrieval:read"],
        category="retrieval",
    ))
