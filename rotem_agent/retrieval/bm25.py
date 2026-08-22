from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

K1 = 1.5
B = 0.75


@dataclass
class Bm25:
    """Lexical ranking over a single matter's chunks.

    Built in memory at query time from term lists stored per chunk. One matter
    holds hundreds of chunks, not millions, so a persistent inverted index would
    add moving parts without buying measurable speed.
    """

    documents: list[list[str]]

    def __post_init__(self) -> None:
        self._counts = [Counter(terms) for terms in self.documents]
        self._lengths = [max(len(terms), 1) for terms in self.documents]
        self._avg_length = sum(self._lengths) / len(self._lengths) if self._lengths else 1.0
        frequency: Counter[str] = Counter()
        for counts in self._counts:
            frequency.update(counts.keys())
        self._doc_frequency = frequency

    def score(self, query_terms: list[str]) -> list[float]:
        total = len(self._counts)
        if not total:
            return []
        scores = [0.0] * total
        for term in set(query_terms):
            document_frequency = self._doc_frequency.get(term, 0)
            if not document_frequency:
                continue
            idf = math.log(1 + (total - document_frequency + 0.5) / (document_frequency + 0.5))
            for index, counts in enumerate(self._counts):
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                length_norm = 1 - B + B * (self._lengths[index] / self._avg_length)
                scores[index] += idf * (frequency * (K1 + 1)) / (frequency + K1 * length_norm)
        return scores
