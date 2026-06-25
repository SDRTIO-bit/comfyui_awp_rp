"""
Retrieval scorer with multiple strategies.

Supports keyword, BM25, and hybrid retrieval strategies.
"""

from dataclasses import dataclass, field
from typing import Optional

from ..core.types import (
    RetrievalDocument,
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from .bm25 import BM25Scorer, FieldWeights
from .tokenizer import tokenize


@dataclass
class RetrievalConfig:
    """Configuration for retrieval."""
    strategy: RetrievalStrategy = "keyword"
    limit: int = 8
    min_score: float = 0.01
    field_weights: Optional[FieldWeights] = None
    priority_weight: float = 0.05
    include_diagnostics: bool = False


@dataclass
class RetrievalHints:
    """Hints for retrieval scoring."""
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)


@dataclass
class RetrievalFilters:
    """Filters for retrieval."""
    entry_ids: Optional[list[str]] = None
    tags_any: Optional[list[str]] = None
    tags_all: Optional[list[str]] = None
    entity_ids_any: Optional[list[str]] = None
    type: Optional[str] = None
    title_contains: Optional[str] = None


class RetrievalScorer:
    """Scorer for document retrieval with multiple strategies."""
    
    def __init__(self, config: Optional[RetrievalConfig] = None):
        self.config = config or RetrievalConfig()
        self._bm25 = BM25Scorer(self.config.field_weights)
    
    def retrieve(
        self,
        query: str,
        documents: list[RetrievalDocument],
        filters: Optional[RetrievalFilters] = None,
        hints: Optional[RetrievalHints] = None,
    ) -> RetrievalResult:
        """Retrieve documents matching the query.
        
        Args:
            query: Query text
            documents: List of documents to search
            filters: Optional filters to apply
            hints: Optional hints for scoring
        
        Returns:
            RetrievalResult with ranked hits
        """
        # Apply filters
        filtered_docs = self._apply_filters(documents, filters)
        
        # Score documents
        if self.config.strategy == "bm25":
            scores = self._bm25.score(filtered_docs, query)
        elif self.config.strategy == "hybrid":
            scores = self._hybrid_score(filtered_docs, query, hints)
        else:  # keyword
            scores = self._keyword_score(filtered_docs, query, hints)
        
        # Apply priority weighting
        if self.config.priority_weight > 0:
            for i, doc in enumerate(filtered_docs):
                if doc.priority is not None:
                    scores[i] += doc.priority * self.config.priority_weight
        
        # Filter by min score
        candidates = [
            (doc, score, idx)
            for idx, (doc, score) in enumerate(zip(filtered_docs, scores))
            if score > 0 and score >= self.config.min_score
        ]
        
        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Take top N
        top_candidates = candidates[:self.config.limit]
        
        # Build hits
        hits: list[RetrievalHit] = []
        query_tokens = tokenize(query)
        
        for rank, (doc, score, source_idx) in enumerate(top_candidates):
            # Find matched fields and terms
            matched_fields, matched_terms = self._find_matches(doc, query_tokens)
            
            hit = RetrievalHit(
                rank=rank + 1,
                score=score,
                source_index=source_idx,
                entry=doc,
                matched_fields=matched_fields,
                matched_terms=matched_terms,
            )
            hits.append(hit)
        
        return RetrievalResult(
            query=query,
            strategy=self.config.strategy,
            total_candidates=len(documents),
            total_after_filter=len(filtered_docs),
            total_matched=len(candidates),
            returned=len(hits),
            hits=hits,
        )
    
    def _apply_filters(
        self,
        documents: list[RetrievalDocument],
        filters: Optional[RetrievalFilters],
    ) -> list[RetrievalDocument]:
        """Apply filters to documents."""
        if not filters:
            return documents
        
        result = []
        for doc in documents:
            # Entry ID filter
            if filters.entry_ids and doc.id not in filters.entry_ids:
                continue
            
            # Tags any filter
            if filters.tags_any:
                if not any(tag in doc.tags for tag in filters.tags_any):
                    continue
            
            # Tags all filter
            if filters.tags_all:
                if not all(tag in doc.tags for tag in filters.tags_all):
                    continue
            
            # Entity IDs filter
            if filters.entity_ids_any:
                if not any(eid in doc.entity_ids for eid in filters.entity_ids_any):
                    continue
            
            # Type filter
            if filters.type and doc.type != filters.type:
                continue
            
            # Title contains filter
            if filters.title_contains:
                if not doc.title or filters.title_contains.lower() not in doc.title.lower():
                    continue
            
            result.append(doc)
        
        return result
    
    def _keyword_score(
        self,
        documents: list[RetrievalDocument],
        query: str,
        hints: Optional[RetrievalHints],
    ) -> list[float]:
        """Simple keyword matching score."""
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return [0.0] * len(documents)
        
        scores: list[float] = []
        for doc in documents:
            score = 0.0
            
            # Check title
            if doc.title:
                title_tokens = set(tokenize(doc.title))
                title_matches = len(query_tokens & title_tokens)
                score += title_matches * 3.0  # Title weight
            
            # Check content
            content_tokens = set(tokenize(doc.content))
            content_matches = len(query_tokens & content_tokens)
            score += content_matches * 1.0  # Content weight
            
            # Check tags
            for tag in doc.tags:
                tag_tokens = set(tokenize(tag))
                tag_matches = len(query_tokens & tag_tokens)
                score += tag_matches * 2.0  # Tag weight
            
            # Check hints
            if hints:
                for hint_tag in hints.tags:
                    if hint_tag in doc.tags:
                        score += 1.0
                for hint_entity in hints.entity_ids:
                    if hint_entity in doc.entity_ids:
                        score += 1.0
            
            scores.append(score)
        
        return scores
    
    def _hybrid_score(
        self,
        documents: list[RetrievalDocument],
        query: str,
        hints: Optional[RetrievalHints],
    ) -> list[float]:
        """Hybrid score combining keyword, BM25, and hints."""
        keyword_scores = self._keyword_score(documents, query, hints)
        bm25_scores = self._bm25.score(documents, query)
        
        # Normalize scores
        max_keyword = max(keyword_scores) if keyword_scores else 1
        max_bm25 = max(bm25_scores) if bm25_scores else 1
        
        if max_keyword == 0:
            max_keyword = 1
        if max_bm25 == 0:
            max_bm25 = 1
        
        # Combine with weights
        weights = {"keyword": 0.45, "bm25": 0.45, "hints": 0.1}
        
        scores: list[float] = []
        for i in range(len(documents)):
            keyword_norm = keyword_scores[i] / max_keyword
            bm25_norm = bm25_scores[i] / max_bm25
            
            # Hints score
            hints_score = 0.0
            if hints:
                doc = documents[i]
                for hint_tag in hints.tags:
                    if hint_tag in doc.tags:
                        hints_score += 0.5
                for hint_entity in hints.entity_ids:
                    if hint_entity in doc.entity_ids:
                        hints_score += 0.5
                if doc.priority:
                    hints_score += doc.priority
            
            combined = (
                weights["keyword"] * keyword_norm +
                weights["bm25"] * bm25_norm +
                weights["hints"] * min(hints_score, 1.0)
            )
            scores.append(combined)
        
        return scores
    
    def _find_matches(
        self,
        doc: RetrievalDocument,
        query_tokens: list[str],
    ) -> tuple[list[str], list[str]]:
        """Find which fields and terms matched."""
        matched_fields: list[str] = []
        matched_terms: list[str] = []
        
        query_set = set(t.lower() for t in query_tokens)
        
        # Check title
        if doc.title:
            title_tokens = set(t.lower() for t in tokenize(doc.title))
            title_matches = query_set & title_tokens
            if title_matches:
                matched_fields.append("title")
                matched_terms.extend(title_matches)
        
        # Check content
        content_tokens = set(t.lower() for t in tokenize(doc.content))
        content_matches = query_set & content_tokens
        if content_matches:
            matched_fields.append("content")
            matched_terms.extend(content_matches)
        
        # Check tags
        for tag in doc.tags:
            tag_tokens = set(t.lower() for t in tokenize(tag))
            tag_matches = query_set & tag_tokens
            if tag_matches:
                if "tags" not in matched_fields:
                    matched_fields.append("tags")
                matched_terms.extend(tag_matches)
        
        return matched_fields, list(set(matched_terms))
