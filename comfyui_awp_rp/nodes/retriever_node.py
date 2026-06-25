"""
Retriever node for searching documents with BM25/keyword/hybrid strategies.
"""

import json
import os
from typing import Any

from ..core.types import RetrievalDocument
from ..core.config import get_config
from ..retrieval.scorer import RetrievalScorer, RetrievalConfig, RetrievalFilters


class AWPRetriever:
    """使用多种策略检索相关文档。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "query": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "搜索查询...",
                    "forceInput": True,
                }),
                "documents_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": '文档JSON数组: [{"id": "1", "content": "...", "title": "...", "tags": [...]}]',
                    "forceInput": True,
                }),
            },
            "optional": {
                "strategy": (["keyword", "bm25", "hybrid", "embedding", "hybrid_semantic"], {"default": "bm25"}),
                "limit": ("INT", {"default": 8, "min": 1, "max": 50}),
                "min_score": ("FLOAT", {"default": 0.01, "min": 0.0, "max": 10.0, "step": 0.01}),
                "filter_tags": ("STRING", {"default": "", "placeholder": "过滤标签（逗号分隔）"}),
                "filter_type": ("STRING", {"default": "", "placeholder": "过滤类型"}),
                "vector_persist_dir": ("STRING", {
                    "default": "",
                    "placeholder": "ChromaDB 持久化目录（可选）",
                }),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("结果文本", "结果JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/检索"
    
    def execute(
        self,
        query: str,
        documents_json: str,
        strategy: str = "bm25",
        limit: int = 8,
        min_score: float = 0.01,
        filter_tags: str = "",
        filter_type: str = "",
        vector_persist_dir: str = "",
    ):
        """Execute retrieval."""
        if not query:
            return ("Error: query is required", "[]")
        
        # Parse documents
        try:
            docs_data = json.loads(documents_json) if documents_json.strip() else []
        except json.JSONDecodeError as e:
            return (f"Error parsing documents JSON: {e}", "[]")
        
        # Convert to RetrievalDocument objects
        documents = []
        for d in docs_data:
            doc = RetrievalDocument(
                id=d.get("id", ""),
                content=d.get("content", ""),
                title=d.get("title"),
                type=d.get("type"),
                tags=d.get("tags", []),
                entity_ids=d.get("entity_ids", []),
                priority=d.get("priority"),
            )
            documents.append(doc)
        
        if not documents:
            return ("(No documents to search)", "[]")
        
        # Configure retriever
        config = RetrievalConfig(
            strategy=strategy,
            limit=limit,
            min_score=min_score,
        )
        
        # Build filters
        filters = None
        if filter_tags or filter_type:
            tag_list = [t.strip() for t in filter_tags.split(",") if t.strip()] if filter_tags else None
            filters = RetrievalFilters(
                tags_any=tag_list,
                type=filter_type if filter_type else None,
            )
            documents = [
                doc for doc in documents
                if _matches_filters(doc, filters)
            ]
            if not documents:
                return ("(No documents to search)", "[]")

        # Execute retrieval
        if strategy in ("embedding", "hybrid_semantic"):
            from ..retrieval.vector_store import VectorStore

            persist_dir = (
                vector_persist_dir.strip()
                or os.path.join(get_config().data_dir, "vectors_runtime", "retriever")
            )
            vector_store = VectorStore(persist_dir, "awp_retriever_runtime")
            vector_docs = [_doc_to_vector_dict(doc) for doc in documents]
            vector_store.delete([doc["id"] for doc in vector_docs if doc.get("id")])
            vector_store.index(vector_docs)

            if strategy == "embedding":
                emb_hits = vector_store.search(query, top_k=limit, min_score=min_score)
                results_text = "\n".join(
                    f"[{rank}. {h.get('metadata', {}).get('title') or h.get('title') or 'Untitled'}] (score: {h.get('score', 0):.3f})\n"
                    f"{str(h.get('content', ''))[:150]}..."
                    for rank, h in enumerate(emb_hits, 1)
                ) or "(No matches found)"
                results_json = json.dumps([
                    {
                        "rank": rank,
                        "score": h.get("score", 0),
                        "id": h.get("id", ""),
                        "title": h.get("metadata", {}).get("title") or h.get("title"),
                        "content": h.get("content", ""),
                        "metadata": h.get("metadata", {}),
                    }
                    for rank, h in enumerate(emb_hits, 1)
                ], ensure_ascii=False, indent=2)
                return (results_text, results_json)

            elif strategy == "hybrid_semantic":
                from ..retrieval.bm25 import BM25Scorer
                from ..retrieval.embedding import HybridRetriever
                # BM25 scores
                bm25 = BM25Scorer()
                bm25_scores = bm25.score(documents, query)
                vector_hits = vector_store.search(
                    query,
                    top_k=max(limit, len(documents)),
                    min_score=0.0,
                )
                vector_scores_by_id = {
                    str(hit.get("id", "")): float(hit.get("score", 0) or 0)
                    for hit in vector_hits
                }
                emb_scores = [vector_scores_by_id.get(doc.id, 0.0) for doc in documents]
                # Hybrid combine
                hybrid = HybridRetriever(alpha=0.3)
                combined = hybrid.score(bm25_scores, emb_scores)
                # Rank
                ranked = sorted(enumerate(combined), key=lambda x: x[1], reverse=True)[:limit]
                lines = []
                json_hits = []
                for rank, (idx, score) in enumerate(ranked, 1):
                    if score < min_score:
                        break
                    doc = documents[idx]
                    lines.append(f"[{rank}. {doc.title or 'Untitled'}] (hybrid: {score:.3f})")
                    lines.append(doc.content[:150] + "..." if len(doc.content) > 150 else doc.content)
                    lines.append("")
                    json_hits.append({
                        "rank": rank,
                        "score": round(score, 4),
                        "id": doc.id,
                        "title": doc.title,
                        "content": doc.content,
                        "bm25_score": round(bm25_scores[idx], 4),
                        "embedding_score": round(emb_scores[idx], 4),
                    })
                results_text = "\n".join(lines) or "(No matches found)"
                results_json = json.dumps(json_hits, ensure_ascii=False, indent=2)
                return (results_text, results_json)

        # Legacy path: keyword/bm25/hybrid
        scorer = RetrievalScorer(config)
        result = scorer.retrieve(query, documents, filters)
        
        # Format output
        if result.hits:
            lines = []
            for hit in result.hits:
                title = hit.entry.title or "Untitled"
                score = f"{hit.score:.2f}"
                content_preview = hit.entry.content[:150] + "..." if len(hit.entry.content) > 150 else hit.entry.content
                lines.append(f"[{hit.rank}. {title}] (score: {score})")
                lines.append(content_preview)
                if hit.matched_terms:
                    lines.append(f"Matched: {', '.join(hit.matched_terms[:5])}")
                lines.append("")
            results_text = "\n".join(lines)
        else:
            results_text = "(No matches found)"
        
        results_json = json.dumps([
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

        return (results_text, results_json)


def _matches_filters(doc: RetrievalDocument, filters: RetrievalFilters) -> bool:
    if filters.type and doc.type != filters.type:
        return False
    if filters.tags_any:
        if not set(filters.tags_any).intersection(set(doc.tags or [])):
            return False
    return True


def _doc_to_vector_dict(doc: RetrievalDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title or "",
        "content": doc.content or "",
        "type": doc.type or "",
        "tags": doc.tags or [],
        "metadata": {
            **(doc.metadata or {}),
            "entity_ids": doc.entity_ids or [],
            "priority": doc.priority,
        },
    }
