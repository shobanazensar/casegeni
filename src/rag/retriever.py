from __future__ import annotations
import math
import re
from collections import Counter
from typing import Iterable, List, Dict, Any


_WORD = re.compile(r"[A-Za-z0-9_\-]+")


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text)]


class EmbeddingAdapter:
    '''
    Lightweight embedding abstraction.
    - Tries sentence-transformers if installed.
    - Falls back to lexical cosine scoring.
    '''

    def __init__(self) -> None:
        self.model = None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self.model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            self.model = None

    def score(self, query: str, docs: list[str]) -> list[float]:
        if self.model:
            try:
                import numpy as np  # type: ignore
                q = self.model.encode([query], normalize_embeddings=True)
                d = self.model.encode(docs, normalize_embeddings=True)
                return [float(np.dot(q[0], x)) for x in d]
            except Exception:
                pass
        return lexical_scores(query, docs)


def lexical_scores(query: str, docs: list[str]) -> list[float]:
    q = Counter(tokenize(query))
    qn = math.sqrt(sum(v * v for v in q.values())) or 1.0
    scores = []
    for doc in docs:
        d = Counter(tokenize(doc))
        dn = math.sqrt(sum(v * v for v in d.values())) or 1.0
        inter = sum(q[t] * d.get(t, 0) for t in q)
        scores.append(inter / (qn * dn))
    return scores


class RAGRetriever:
    def __init__(self, chunk_size: int = 700, overlap: int = 120) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.embedder = EmbeddingAdapter()

    def chunk(self, text: str) -> list[str]:
        words = text.split()
        if not words:
            return []
        chunks = []
        i = 0
        while i < len(words):
            chunks.append(" ".join(words[i:i + self.chunk_size]))
            i += max(1, self.chunk_size - self.overlap)
        return chunks

    def retrieve(self, text: str, query: str, top_k: int = 4) -> list[dict]:
        chunks = self.chunk(text)
        if not chunks:
            return []
        scores = self.embedder.score(query, chunks)
        pairs = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [{"content": c, "score": round(s, 4)} for c, s in pairs]
