"""One FastEmbed instance per process. Fail-loud, thread-pooled, length-guarded.

Fixes the ask.nkngo defects: env-driven cache dir (no hardcoded path), no
silent-None failure path (typed exception), sync ONNX calls off the event loop.
"""
import logging

import anyio
from fastembed import TextEmbedding

from .config import Settings

log = logging.getLogger("tottie.embeddings")

# BGE scores queries best with the retrieval instruction; documents embed bare.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# bge-small hard limit is 512 tokens; chars/4 heuristic keeps us under it.
CHAR_BUDGET = 2048
# bge-small-en-v1.5 native width. schema.sql vector(384) must match; the health
# test asserts embed dim so a model swap fails loudly instead of silently.
NATIVE_DIM = 384


class EmbedderUnavailable(RuntimeError):
    """The embedding model cannot load. Raised, never returned as None."""


class Embedder:
    def __init__(self, settings: Settings) -> None:
        if settings.embedder != "fastembed":
            raise EmbedderUnavailable(f"unknown embedder {settings.embedder!r}")
        try:
            self._model = TextEmbedding(
                model_name=settings.embed_model,
                cache_dir=settings.embedding_cache_dir,
                threads=4,
            )
        except Exception as e:
            raise EmbedderUnavailable(
                f"cannot load {settings.embed_model}: {e}"
            ) from e
        self.model_name = settings.embed_model
        log.info("embedder ready: %s", self.model_name)

    @property
    def dim(self) -> int:
        return NATIVE_DIM

    async def embed(self, text: str, *, is_query: bool = False) -> tuple[list[float], bool]:
        """Embed one text. Returns (vector, truncated). Truncation is flagged,
        never silent — the Scribe (W1) decides summarise vs chunk."""
        clipped, truncated = self._clip(text)
        payload = (QUERY_PREFIX + clipped) if is_query else clipped
        vecs = await anyio.to_thread.run_sync(
            lambda: list(self._model.embed([payload]))
        )
        vec = [float(x) for x in vecs[0]]
        if len(vec) != NATIVE_DIM:
            raise EmbedderUnavailable(
                f"width {len(vec)} != {NATIVE_DIM}; model/column mismatch"
            )
        return vec, truncated

    @staticmethod
    def _clip(text: str) -> tuple[str, bool]:
        if len(text) <= CHAR_BUDGET:
            return text, False
        return text[:CHAR_BUDGET], True
