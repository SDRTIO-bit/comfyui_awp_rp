"""
BM25 scoring for retrieval.

Standard BM25 implementation with k1=1.2, b=0.75.
Supports field-weighted scoring.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from ..core.types import RetrievalDocument
from .tokenizer import tokenize


# BM25 parameters
K1 = 1.2
B = 0.75


@dataclass
class FieldWeights:
    """Weights for different document fields."""
    title: float = 3.0
    content: float = 1.0
    tags: float = 2.0
    entity_ids: float = 2.0
    type: float = 1.5


DEFAULT_FIELD_WEIGHTS = FieldWeights()


@dataclass
class DocumentTokens:
    """Tokenized document with field information."""
    doc: RetrievalDocument
    title_tokens: list[str] = field(default_factory=list)
    content_tokens: list[str] = field(default_factory=list)
    tags_tokens: list[str] = field(default_factory=list)
    entity_tokens: list[str] = field(default_factory=list)
    type_tokens: list[str] = field(default_factory=list)
    weighted_tokens: list[str] = field(default_factory=list)


class BM25Scorer:
    """BM25 scoring for document retrieval."""
    
    def __init__(self, field_weights: Optional[FieldWeights] = None):
        self.weights = field_weights or DEFAULT_FIELD_WEIGHTS
    
    def score(
        self,
        docs: list[RetrievalDocument],
        query: str,
    ) -> list[float]:
        """Compute BM25 scores for documents against a query.
        
        Args:
            docs: List of documents to score
            query: Query text
        
        Returns:
            List of scores (one per document)
        """
        if not docs:
            return []
        
        query_tokens = tokenize(query)
        if not query_tokens:
            return [0.0] * len(docs)
        
        # Tokenize all documents
        doc_data = [self._tokenize_doc(doc) for doc in docs]
        
        # Compute document lengths (weighted)
        doc_lengths = [len(d.weighted_tokens) for d in doc_data]
        avg_dl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1
        
        # Compute document frequency for each query token
        token_df: dict[str, int] = {}
        for qt in query_tokens:
            qt_lower = qt.lower()
            count = 0
            for dd in doc_data:
                if any(t.lower() == qt_lower for t in dd.weighted_tokens):
                    count += 1
            token_df[qt] = count
        
        # Compute IDF for each token
        N = len(docs)
        idfs: dict[str, float] = {}
        for qt in query_tokens:
            n = token_df.get(qt, 0)
            # IDF = log((N - n + 0.5) / (n + 0.5) + 1)
            idfs[qt] = math.log((N - n + 0.5) / (n + 0.5) + 1)
        
        # Score each document
        scores: list[float] = []
        for idx, dd in enumerate(doc_data):
            score = 0.0
            dl = doc_lengths[idx]
            weighted_lower = [t.lower() for t in dd.weighted_tokens]
            
            for qt in query_tokens:
                qt_lower = qt.lower()
                f = weighted_lower.count(qt_lower)
                if f == 0:
                    continue
                
                idf = idfs[qt]
                numerator = f * (K1 + 1)
                denominator = f + K1 * (1 - B + B * (dl / (avg_dl or 1)))
                score += idf * (numerator / denominator)
            
            scores.append(score)
        
        return scores
    
    def _tokenize_doc(self, doc: RetrievalDocument) -> DocumentTokens:
        """Tokenize a document with field weights."""
        result = DocumentTokens(doc=doc)
        
        # Tokenize each field
        result.title_tokens = tokenize(doc.title or "")
        result.content_tokens = tokenize(doc.content)
        result.tags_tokens = []
        for tag in doc.tags:
            result.tags_tokens.extend(tokenize(tag))
        result.entity_tokens = []
        for eid in doc.entity_ids:
            result.entity_tokens.extend(tokenize(eid))
        result.type_tokens = tokenize(doc.type or "")
        
        # Build weighted token list
        weighted: list[str] = []
        
        def repeat(tokens: list[str], weight: float) -> None:
            count = max(1, round(weight))
            for _ in range(count):
                weighted.extend(tokens)
        
        repeat(result.title_tokens, self.weights.title)
        repeat(result.content_tokens, self.weights.content)
        repeat(result.tags_tokens, self.weights.tags)
        repeat(result.entity_tokens, self.weights.entity_ids)
        repeat(result.type_tokens, self.weights.type)
        
        result.weighted_tokens = weighted
        return result
