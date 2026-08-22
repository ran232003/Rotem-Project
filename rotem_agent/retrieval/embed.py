from __future__ import annotations

import hashlib
import os
from typing import Protocol, Sequence

import numpy as np

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONS = 768


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def unit(vector: Sequence[float]) -> np.ndarray:
    """L2-normalise so cosine similarity is a plain dot product.

    Also required for correctness when a truncated output dimensionality is
    requested, because the shortened vector is no longer unit length.
    """
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    return array if norm == 0.0 else array / norm


class GeminiEmbedder:
    """Gemini embeddings, with the batch behaviour verified rather than assumed.

    `gemini-embedding-001` returns one vector per input. `gemini-embedding-2`
    accepts a list and returns a single vector with no error, which would pair
    each chunk with another chunk's vector. So the returned count is checked and
    the batch is redone one item at a time if it does not match.

    The default is the older model precisely because it batches, making ingest of
    a large matter far faster. There is no evaluation harness yet to show the
    newer model retrieves Hebrew better, so paying that latency on faith is not
    justified; set GEMINI_EMBED_MODEL to change it.
    """

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        dimensions: int = DEFAULT_DIMENSIONS,
        batch_size: int = 32,
    ) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model or os.getenv("GEMINI_EMBED_MODEL", DEFAULT_MODEL).strip()
        self._dimensions = dimensions
        self._batch_size = batch_size

    @property
    def name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            vectors.extend(self._embed_batch(batch, "RETRIEVAL_DOCUMENT"))
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed_batch([text], "RETRIEVAL_QUERY")[0]

    def _embed_batch(self, batch: list[str], task_type: str) -> list[np.ndarray]:
        returned = self._call(batch, task_type)
        if len(returned) == len(batch):
            return returned
        return [self._call([text], task_type)[0] for text in batch]

    def _call(self, texts: list[str], task_type: str) -> list[np.ndarray]:
        from google.genai import types

        response = self._client.models.embed_content(
            model=self._model,
            contents=list(texts),
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self._dimensions,
            ),
        )
        return [unit(embedding.values) for embedding in (response.embeddings or [])]


class HashEmbedder:
    """Deterministic offline embedder, for tests and for inspecting the index.

    Encodes term overlap rather than meaning, so it cannot stand in for the real
    model in a quality judgement. It exists so the store, the fusion and the
    ingest path can be tested without network calls.
    """

    def __init__(self, dimensions: int = 64) -> None:
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return f"hash-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)

    def _vector(self, text: str) -> np.ndarray:
        from rotem_agent.retrieval.hebrew import index_terms

        vector = np.zeros(self._dimensions, dtype=np.float32)
        for term in index_terms(text):
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            vector[int.from_bytes(digest, "big") % self._dimensions] += 1.0
        return unit(vector)
