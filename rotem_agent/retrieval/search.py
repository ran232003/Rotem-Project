from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rotem_agent.retrieval.bm25 import Bm25
from rotem_agent.retrieval.embed import Embedder
from rotem_agent.retrieval.hebrew import index_terms
from rotem_agent.retrieval.store import ChunkStore, StoredChunk

# Rank-fusion constant. 60 is the value from the original reciprocal rank fusion
# work and damps the difference between the top few ranks, which is what we want:
# a passage found by both rankers should beat one found emphatically by either.
RRF_K = 60


@dataclass(frozen=True)
class Hit:
    rel_path: str
    chunk_index: int
    text: str
    score: float
    lexical_rank: int | None
    vector_rank: int | None

    @property
    def citation(self) -> str:
        return f"{self.rel_path}#{self.chunk_index}"

    @property
    def found_by(self) -> str:
        if self.lexical_rank is not None and self.vector_rank is not None:
            return "both"
        return "wording" if self.lexical_rank is not None else "meaning"


def search(
    store: ChunkStore,
    matter: str,
    query: str,
    embedder: Embedder | None = None,
    *,
    top_k: int = 6,
    candidates: int = 30,
) -> list[Hit]:
    """Hybrid retrieval over one matter.

    Two rankers are combined because neither is sufficient alone here. Semantic
    search matches on meaning, which is actively wrong for visa classes: ב/1 and
    א/5 sit close together in vector space but are legally unrelated. Lexical
    search gets those exactly right and is useless when the client describes a
    concept in different words from the file.
    """
    chunks = store.load_chunks(matter)
    if not chunks:
        return []

    lexical = _rank_lexical(chunks, query, candidates)
    vector = _rank_vector(chunks, query, embedder, candidates)

    fused: dict[int, float] = {}
    for ranking in (lexical, vector):
        for rank, position in enumerate(ranking):
            fused[position] = fused.get(position, 0.0) + 1.0 / (RRF_K + rank + 1)

    lexical_positions = {position: rank for rank, position in enumerate(lexical)}
    vector_positions = {position: rank for rank, position in enumerate(vector)}

    ordered = sorted(fused.items(), key=lambda pair: pair[1], reverse=True)[:top_k]
    return [
        Hit(
            rel_path=chunks[position].rel_path,
            chunk_index=chunks[position].idx,
            text=chunks[position].text,
            score=score,
            lexical_rank=lexical_positions.get(position),
            vector_rank=vector_positions.get(position),
        )
        for position, score in ordered
    ]


def _rank_lexical(chunks: list[StoredChunk], query: str, limit: int) -> list[int]:
    terms = index_terms(query)
    if not terms:
        return []
    scores = Bm25([chunk.terms for chunk in chunks]).score(terms)
    ranked = [i for i, score in sorted(enumerate(scores), key=lambda p: p[1], reverse=True) if score > 0]
    return ranked[:limit]


def _rank_vector(
    chunks: list[StoredChunk], query: str, embedder: Embedder | None, limit: int
) -> list[int]:
    if embedder is None:
        return []
    usable = [i for i, chunk in enumerate(chunks) if chunk.embedding is not None]
    if not usable:
        return []

    matrix = np.vstack([chunks[i].embedding for i in usable])
    query_vector = embedder.embed_query(query)
    if matrix.shape[1] != query_vector.shape[0]:
        # The index was built with a different model or dimensionality. Silently
        # comparing mismatched vectors would return confident nonsense.
        raise ValueError(
            f"Index holds {matrix.shape[1]}-dimension vectors but the query embedder "
            f"produced {query_vector.shape[0]}. Re-run ingest after changing model."
        )

    similarities = matrix @ query_vector
    order = np.argsort(-similarities)[:limit]
    return [usable[int(i)] for i in order]
