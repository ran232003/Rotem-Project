"""Hybrid retrieval over a matter's documents: lexical BM25 fused with vectors."""

from rotem_agent.retrieval.embed import Embedder, GeminiEmbedder, HashEmbedder
from rotem_agent.retrieval.ingest import IngestSummary, ingest_matter
from rotem_agent.retrieval.search import Hit, search
from rotem_agent.retrieval.store import ChunkStore

__all__ = [
    "ChunkStore",
    "Embedder",
    "GeminiEmbedder",
    "HashEmbedder",
    "Hit",
    "IngestSummary",
    "ingest_matter",
    "search",
]
