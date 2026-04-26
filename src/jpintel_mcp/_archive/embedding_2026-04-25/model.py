"""Encoder wrapper with graceful fallback to a deterministic stub.

If sentence-transformers or the HF hub are unavailable we fall back to a
deterministic 384d random vector (seeded by text hash) so the rest of the
pipeline -- schema, storage, search API -- can be interface-tested without
network.  Stub vectors are obviously useless for real retrieval; the report
flags this when active.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Iterable, List

import numpy as np

from .config import (
    DEFAULT_MODEL,


    EMBED_DIM,
    MODEL_PREFIX_PASSAGE,
    MODEL_PREFIX_QUERY,
    STUB_MODEL,
)


# --- AUTO: SCHEMA_GUARD_BLOCK (Wave 10 infra hardening) ---
import sys as _sg_sys
from pathlib import Path as _sg_Path
_sg_sys.path.insert(0, str(_sg_Path(__file__).resolve().parent.parent))
try:
    from scripts.schema_guard import assert_am_entities_schema as _sg_check
except Exception:  # pragma: no cover - schema_guard must exist in prod
    _sg_check = None
if __name__ == "__main__" and _sg_check is not None:
    _sg_check("/tmp/autonomath_infra_2026-04-24/autonomath.db")
# --- END SCHEMA_GUARD_BLOCK ---

log = logging.getLogger(__name__)


@dataclass
class EncodeResult:
    vectors: np.ndarray  # shape (n, EMBED_DIM), float32, L2-normalised
    model_name: str
    is_stub: bool


class Encoder:
    """Lazy sentence-transformer wrapper with stub fallback."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._st = None
        self.is_stub = False
        self._load()

    def _load(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            log.info("loading sentence-transformer model=%s", self.model_name)
            self._st = SentenceTransformer(self.model_name)
            # Newer sentence-transformers rename get_sentence_embedding_dimension
            # to get_embedding_dimension; support both.
            dim_fn = getattr(
                self._st, "get_embedding_dimension", None
            ) or self._st.get_sentence_embedding_dimension
            dim = dim_fn()
            if dim != EMBED_DIM:
                log.warning(
                    "model dim=%s but EMBED_DIM=%s -- set AUTONOMATH_EMBED_DIM",
                    dim,
                    EMBED_DIM,
                )
        except Exception as exc:  # pragma: no cover (network / offline)
            log.warning("falling back to stub encoder: %s", exc)
            self._st = None
            self.is_stub = True
            self.model_name = STUB_MODEL

    # -----------------------------------------------------------------
    def encode(
        self,
        texts: Iterable[str],
        *,
        kind: str = "passage",
        batch_size: int = 32,
    ) -> EncodeResult:
        texts = list(texts)
        if not texts:
            return EncodeResult(
                vectors=np.zeros((0, EMBED_DIM), dtype=np.float32),
                model_name=self.model_name,
                is_stub=self.is_stub,
            )

        if self.is_stub:
            vecs = np.vstack([_stub_vector(t) for t in texts])
            return EncodeResult(
                vectors=vecs, model_name=STUB_MODEL, is_stub=True
            )

        prefix = MODEL_PREFIX_QUERY if kind == "query" else MODEL_PREFIX_PASSAGE
        prepped = [prefix + t for t in texts]
        vecs = self._st.encode(
            prepped,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
        return EncodeResult(vectors=vecs, model_name=self.model_name, is_stub=False)


def _stub_vector(text: str) -> np.ndarray:
    """Deterministic 384d vector from text hash; L2-normalised."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
    v = rng.standard_normal(EMBED_DIM).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-9
    return v
