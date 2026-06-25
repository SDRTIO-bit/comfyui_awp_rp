"""
Embedding-based semantic similarity search for retrieval.

Lightweight approach: build TF-IDF style vectors from tokenized text
and use cosine similarity. No external model dependencies — works with
the existing tokenizer infrastructure.

For Chinese text, uses character bigrams when jieba is unavailable
to provide semantic granularity at sub-word level.

Combined with BM25 via HybridRetriever for best results.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Optional

from ..core.types import RetrievalDocument
from .tokenizer import tokenize, JIEBA_AVAILABLE


def _tokenize_with_bigram_fallback(text: str) -> list[str]:
    """Tokenize text, falling back to character bigrams for Chinese when jieba unavailable.

    Character bigrams (2-char sliding window) provide sub-word granularity
    for CJK text, significantly improving recall over single-token fallback.
    """
    if not text:
        return []

    tokens = tokenize(text)

    # If jieba is available or text has no CJK, return as-is
    if JIEBA_AVAILABLE:
        return tokens

    # Check if tokens are large CJK chunks (jieba fallback merged everything)
    cjk_tokens = [t for t in tokens if any('\u4e00' <= c <= '\u9fff' for c in t)]
    if not cjk_tokens:
        return tokens

    # Replace large CJK tokens with character bigrams
    result: list[str] = []
    for t in tokens:
        is_cjk = any('\u4e00' <= c <= '\u9fff' for c in t)
        if is_cjk and len(t) > 1:
            # Generate 2-char sliding window bigrams
            for i in range(len(t) - 1):
                result.append(t[i:i + 2])
        elif is_cjk:
            result.append(t)
        else:
            result.append(t)
    return result


class TfidfVectorizer:
    """Build sparse TF-IDF vectors from tokenized documents.

    Uses the standard TF-IDF formula:
      TF(t,d) = count(t,d) / |d|
      IDF(t)  = log((N + 1) / (df(t) + 1)) + 1
      TF-IDF(t,d) = TF(t,d) * IDF(t)
    """

    def __init__(self):
        self._idf: dict[str, float] = {}
        self._vocab: set[str] = set()

    def fit(self, documents: list[list[str]]) -> None:
        """Compute IDF values from document collection."""
        N = len(documents)
        self._vocab = set()
        df: Counter = Counter()

        for doc in documents:
            unique = set(t.lower() for t in doc if len(t) >= 1)
            self._vocab.update(unique)
            df.update(unique)

        for term in self._vocab:
            self._idf[term] = math.log((N + 1) / (df.get(term, 0) + 1)) + 1

    def transform(self, tokens: list[str]) -> dict[str, float]:
        """Convert token list to TF-IDF vector (sparse dict)."""
        if not tokens:
            return {}

        lowered = [t.lower() for t in tokens if len(t) >= 1]
        if not lowered:
            return {}

        total = len(lowered)
        tf = Counter(lowered)
        vector: dict[str, float] = {}

        for term, count in tf.items():
            if term in self._idf:
                tf_val = count / total
                vector[term] = tf_val * self._idf[term]

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vector.values()))
        if norm > 0:
            for term in vector:
                vector[term] /= norm

        return vector


def cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors.

    Since both vectors are already L2-normalized, this is just the dot product.
    """
    if not vec1 or not vec2:
        return 0.0

    # Compute dot product over intersection
    smaller = vec1 if len(vec1) < len(vec2) else vec2
    larger = vec2 if len(vec1) < len(vec2) else vec1

    score = 0.0
    for term in smaller:
        if term in larger:
            score += smaller[term] * larger[term]

    return min(max(score, 0.0), 1.0)


class EmbeddingRetriever:
    """TF-IDF vector-based semantic search.

    Builds document vectors from tokenized content and scores queries
    using cosine similarity against the document vectors.
    """

    def __init__(self):
        self._vectorizer = TfidfVectorizer()
        self._doc_vectors: list[dict[str, float]] = []
        self._docs: list[RetrievalDocument] = []
        self._fitted = False

    def index(self, documents: list[RetrievalDocument]) -> None:
        """Build TF-IDF index from documents."""
        self._docs = documents

        # Tokenize all documents (with bigram fallback for Chinese)
        all_tokens: list[list[str]] = []
        for doc in documents:
            doc_tokens = _tokenize_with_bigram_fallback(doc.content)
            if doc.title:
                doc_tokens.extend(_tokenize_with_bigram_fallback(doc.title))
            for tag in doc.tags:
                doc_tokens.extend(_tokenize_with_bigram_fallback(tag))
            all_tokens.append(doc_tokens)

        # Fit vectorizer
        self._vectorizer.fit(all_tokens)

        # Transform documents
        self._doc_vectors = [self._vectorizer.transform(tokens) for tokens in all_tokens]
        self._fitted = True

    def score(self, query: str) -> list[float]:
        """Score all indexed documents against a query using cosine similarity.

        Returns:
            List of scores (one per document), range [0.0, 1.0].
        """
        if not self._fitted or not self._doc_vectors:
            return []

        query_tokens = _tokenize_with_bigram_fallback(query)
        query_vec = self._vectorizer.transform(query_tokens)

        return [cosine_similarity(query_vec, dv) for dv in self._doc_vectors]

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.05,
    ) -> list[dict[str, Any]]:
        """Search indexed documents and return top-k results.

        Returns:
            List of {rank, score, document} dicts.
        """
        scores = self.score(query)
        if not scores:
            return []

        # Build ranked results
        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )

        results: list[dict[str, Any]] = []
        for rank, (idx, score) in enumerate(ranked[:top_k], 1):
            if score < min_score:
                break
            results.append({
                "rank": rank,
                "score": round(score, 4),
                "document": {
                    "id": self._docs[idx].id,
                    "title": self._docs[idx].title,
                    "content": self._docs[idx].content[:300],
                    "type": self._docs[idx].type,
                    "tags": self._docs[idx].tags,
                },
            })

        return results


class HybridRetriever:
    """Combined BM25 + embedding retrieval with weighted scoring.

    Uses configurable alpha to balance keyword (BM25) vs semantic (embedding):
      hybrid_score = alpha * bm25_norm + (1 - alpha) * embedding_score
    """

    def __init__(self, alpha: float = 0.3):
        """
        Args:
            alpha: BM25 weight (0.0-1.0). Default 0.3 leans toward semantic.
        """
        self._alpha = max(0.0, min(1.0, alpha))

    def score(
        self,
        bm25_scores: list[float],
        embedding_scores: list[float],
    ) -> list[float]:
        """Combine BM25 and embedding scores into hybrid scores."""
        if not bm25_scores or not embedding_scores:
            return bm25_scores or embedding_scores

        assert len(bm25_scores) == len(embedding_scores)

        # Normalize BM25 to [0, 1]
        bm25_norm = _minmax_norm(bm25_scores)

        hybrid = []
        for b, e in zip(bm25_norm, embedding_scores):
            hybrid.append(self._alpha * b + (1.0 - self._alpha) * e)

        return hybrid


def _minmax_norm(values: list[float]) -> list[float]:
    """Min-max normalize a list to [0, 1]."""
    if not values:
        return []
    mn = min(values)
    mx = max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]
