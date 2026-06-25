"""
ChromaDB-backed vector store for semantic memory retrieval.

Provides a persistent vector database for long-term memory and worldbook
entries. Falls back gracefully to TF-IDF (retrieval/embedding.py) if
ChromaDB is not installed.

Install: pip install chromadb

Architecture:
  VectorStore
    ├── index(documents)      — batch embed + store
    ├── search(query, top_k)  — semantic similarity search
    └── delete(ids)           — remove entries

Uses the LLM provider's embedding API (via llm_router) or a local
sentence-transformers model if available.
"""

from __future__ import annotations

import json
from typing import Any, Optional


try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class VectorStore:
    """ChromaDB-backed vector store with graceful TF-IDF fallback.

    When ChromaDB is unavailable, delegates to EmbeddingRetriever
    from retrieval/embedding.py for TF-IDF based search.
    """

    def __init__(self, persist_dir: str, collection_name: str = "awp_memories"):
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None
        self._fallback: Any = None
        self._available = False

        if CHROMADB_AVAILABLE:
            try:
                import os
                os.makedirs(persist_dir, exist_ok=True)
                self._client = chromadb.PersistentClient(path=persist_dir)
                # Get or create collection
                try:
                    self._collection = self._client.get_collection(collection_name)
                except Exception:
                    self._collection = self._client.create_collection(
                        name=collection_name,
                        metadata={"hnsw:space": "cosine"},
                    )
                self._available = True
            except Exception:
                self._available = False

        if not self._available:
            # Fallback to TF-IDF
            from ..retrieval.embedding import EmbeddingRetriever
            from ..core.types import RetrievalDocument
            self._fallback = EmbeddingRetriever()
            self._fallback_docs: list[RetrievalDocument] = []

    @property
    def is_available(self) -> bool:
        return self._available

    def index(self, documents: list[dict[str, Any]], embedder: Any = None) -> int:
        """Index documents into the vector store.

        Args:
            documents: List of {id, content, title?, tags?, metadata?} dicts.
            embedder: Optional embedding function. If None, uses ChromaDB default.

        Returns:
            Number of documents indexed.
        """
        if not documents:
            return 0

        if self._available and self._collection:
            ids = []
            contents = []
            metadatas = []
            for i, doc in enumerate(documents):
                doc_id = doc.get("id", f"doc_{i}")
                ids.append(doc_id)
                content = doc.get("content", "") or ""
                if doc.get("title"):
                    content = f"{doc['title']}: {content}"
                contents.append(content)
                metadatas.append({
                    "title": doc.get("title", ""),
                    "tags": ",".join(doc.get("tags", [])),
                    "type": doc.get("type", ""),
                })

            if embedder:
                embeddings = embedder(contents)
                self._collection.add(
                    ids=ids, documents=contents,
                    metadatas=metadatas, embeddings=embeddings,
                )
            else:
                self._collection.add(
                    ids=ids, documents=contents, metadatas=metadatas,
                )
            return len(ids)

        # Fallback to TF-IDF
        from ..core.types import RetrievalDocument
        rdocs = [RetrievalDocument(
            id=d.get("id", f"doc_{i}"),
            content=d.get("content", ""),
            title=d.get("title"),
            type=d.get("type"),
            tags=d.get("tags", []),
        ) for i, d in enumerate(documents)]
        self._fallback_docs.extend(rdocs)
        self._fallback.index(self._fallback_docs)
        return len(rdocs)

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Semantic search the vector store.

        Args:
            query: Search query text.
            top_k: Maximum results to return.
            min_score: Minimum similarity threshold.

        Returns:
            List of {id, content, score, metadata} dicts.
        """
        if not query:
            return []

        if self._available and self._collection:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
            )
            if not results or not results.get("ids"):
                return []

            hits: list[dict[str, Any]] = []
            ids = results["ids"][0] if results["ids"] else []
            docs = results["documents"][0] if results.get("documents") else []
            distances = results["distances"][0] if results.get("distances") else []
            metas = results["metadatas"][0] if results.get("metadatas") else []

            for i in range(len(ids)):
                score = 1.0 - float(distances[i]) if i < len(distances) else 0.0
                if score < min_score:
                    continue
                hits.append({
                    "id": ids[i],
                    "content": docs[i] if i < len(docs) else "",
                    "score": round(score, 4),
                    "metadata": metas[i] if i < len(metas) else {},
                })
            return hits

        # Fallback
        if self._fallback:
            return self._fallback.search(query, top_k=top_k, min_score=min_score)

        return []

    def delete(self, ids: list[str]) -> int:
        """Delete documents by ID. Returns count deleted."""
        if self._available and self._collection:
            try:
                self._collection.delete(ids=ids)
                return len(ids)
            except Exception:
                return 0
        if self._fallback and hasattr(self, "_fallback_docs"):
            id_set = set(ids)
            before = len(self._fallback_docs)
            self._fallback_docs = [
                doc for doc in self._fallback_docs
                if doc.id not in id_set
            ]
            deleted = before - len(self._fallback_docs)
            if deleted:
                self._fallback.index(self._fallback_docs)
            return deleted
        return 0

    def count(self) -> int:
        """Return total indexed document count."""
        if self._available and self._collection:
            return self._collection.count()
        return len(self._fallback_docs) if hasattr(self, '_fallback_docs') else 0


def create_memory_store(project_root: str) -> VectorStore:
    """Factory: create a VectorStore for a project's memory.

    Persists to {project_root}/.awp/vectors/
    """
    import os
    persist_dir = os.path.join(project_root, ".awp", "vectors")
    os.makedirs(persist_dir, exist_ok=True)
    return VectorStore(persist_dir, "awp_memories")


def create_worldbook_store(project_root: str) -> VectorStore:
    """Factory: create a VectorStore for worldbook entries.

    Persists to {project_root}/.awp/vectors_wb/
    """
    import os
    persist_dir = os.path.join(project_root, ".awp", "vectors_wb")
    os.makedirs(persist_dir, exist_ok=True)
    return VectorStore(persist_dir, "awp_worldbook")
