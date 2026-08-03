"""Product embeddings.

The default is a deterministic hashing embedding: no API key, no network, stable
output. It is good enough for the MVP's only use — surfacing previously
confirmed HS codes for near-identical products — and the pgvector column,
indexing, and query path are all real, so swapping in a hosted embedder is a
one-class change.
"""

from __future__ import annotations

import hashlib
import math
import re

from app.models.product import EMBEDDING_DIM

_TOKEN_RE = re.compile(r"[\w؀-ۿ]+", re.UNICODE)


class HashingEmbeddingProvider:
    name = "hashing_embedding"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            # Sign from a different digest byte so related tokens don't all pile
            # into the same direction.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]
