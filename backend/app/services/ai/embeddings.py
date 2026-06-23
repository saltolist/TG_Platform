"""Embedding backends for RAG (Phase 2, step 4).

Two backends behind a common interface:
- LocalEmbeddingBackend: fastembed (multilingual-e5-small, ONNX/CPU, no API key needed).
- RemoteEmbeddingBackend: OpenAI-compatible /v1/embeddings endpoint (BYOK).

resolve_embedding_backend() picks the active backend for a user based on their
AI profile and global config.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from abc import ABC, abstractmethod
from typing import Any, Mapping

import httpx

from app.core.config import Settings, get_settings
from app.db.models import User
from app.services.ai.keys import LlmModelKey, resolve_api_key
from app.services.ai.providers import EmbeddingProviderSpec, embeddings_url, get_embedding_provider_spec

logger = logging.getLogger(__name__)

# Default local embedding model (must be in fastembed TextEmbedding.list_supported_models())
DEFAULT_LOCAL_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# fastembed uses "query:" / "passage:" prefixes for e5 models only
_E5_QUERY_PREFIX = "query: "
_E5_PASSAGE_PREFIX = "passage: "


class EmbeddingBackend(ABC):
    """Protocol for embedding backends."""

    @property
    @abstractmethod
    def model_key(self) -> str:
        """Stable identifier: '<source>:<model_name>'."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Vector dimensionality."""

    @abstractmethod
    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed document passages (for indexing)."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query (for retrieval)."""


# ──────────────────────────────────────────────────────────────────────────────
# Local backend (fastembed, no API key)
# ──────────────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=8)
def _get_model_dim(model_name: str) -> int:
    """Look up output dimension from fastembed model registry."""
    try:
        from fastembed import TextEmbedding  # type: ignore[import-untyped]
        for entry in TextEmbedding.list_supported_models():
            if entry.get("model") == model_name:
                return int(entry["dim"])
    except Exception:
        pass
    return 384


def _uses_e5_prefixes(model_name: str) -> bool:
    return "e5" in model_name.lower()


@functools.lru_cache(maxsize=4)
def _get_fastembed_model(model_name: str):  # type: ignore[return]
    """Lazy-load and cache fastembed TextEmbedding model (thread-safe singleton)."""
    try:
        from fastembed import TextEmbedding  # type: ignore[import-untyped]
        return TextEmbedding(model_name=model_name)
    except Exception as exc:
        logger.warning("Failed to load fastembed model %r: %s", model_name, exc)
        return None


class LocalEmbeddingBackend(EmbeddingBackend):
    """CPU-local embeddings via fastembed (ONNX/CPU, no API key required)."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or DEFAULT_LOCAL_EMBEDDING_MODEL
        self._dim = _get_model_dim(self._model_name)

    @property
    def model_key(self) -> str:
        return f"local:{self._model_name}"

    @property
    def dim(self) -> int:
        return self._dim

    def _prefix_passages(self, texts: list[str]) -> list[str]:
        if _uses_e5_prefixes(self._model_name):
            return [_E5_PASSAGE_PREFIX + t for t in texts]
        return texts

    def _prefix_query(self, text: str) -> list[str]:
        if _uses_e5_prefixes(self._model_name):
            return [_E5_QUERY_PREFIX + text]
        return [text]

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        model = _get_fastembed_model(self._model_name)
        if model is None:
            raise RuntimeError(f"fastembed model {self._model_name!r} is not available")
        return [vec.tolist() for vec in model.embed(texts)]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = self._prefix_passages(texts)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._embed_sync, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        prefixed = self._prefix_query(text)
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(None, self._embed_sync, prefixed)
        return vecs[0]


# ──────────────────────────────────────────────────────────────────────────────
# Remote backend (OpenAI-compatible /v1/embeddings)
# ──────────────────────────────────────────────────────────────────────────────

class RemoteEmbeddingBackend(EmbeddingBackend):
    """OpenAI-compatible remote embeddings (BYOK)."""

    def __init__(self, spec: EmbeddingProviderSpec, api_key: str, model: str | None = None) -> None:
        self._spec = spec
        self._api_key = api_key
        self._model = model or spec.default_model
        self._dim = spec.dim

    @property
    def model_key(self) -> str:
        return f"{self._spec.name.lower()}:{self._model}"

    @property
    def dim(self) -> int:
        return self._dim

    async def _call(self, texts: list[str]) -> list[list[float]]:
        url = embeddings_url(self._spec)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"input": texts, "model": self._model},
            )
            resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return await self._call(texts)

    async def embed_query(self, text: str) -> list[float]:
        vecs = await self._call([text])
        return vecs[0]


# ──────────────────────────────────────────────────────────────────────────────
# Backend resolver
# ──────────────────────────────────────────────────────────────────────────────

def resolve_embedding_backend(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings | None = None,
) -> EmbeddingBackend:
    """Return the active EmbeddingBackend for this user.

    Resolution order:
    1. If EMBEDDING_PROVIDER_BYOK is set in config AND the user has a resolvable
       API key for that provider → RemoteEmbeddingBackend.
    2. Fallback: LocalEmbeddingBackend (no key required, always available).
    """
    settings = settings or get_settings()
    byok_provider = (settings.embedding_provider_byok or "").strip()

    if byok_provider:
        spec = get_embedding_provider_spec(byok_provider)
        if spec is not None:
            # Resolve API key using the same mechanism as LLM keys
            embeddings_model_entry: dict[str, Any] = ai_profile.get("embeddingsModel") or {}
            raw_key = str(embeddings_model_entry.get("apiKey") or "").strip()
            resolution = resolve_api_key(
                LlmModelKey(provider=byok_provider, api_key=raw_key),
                user,
                settings,
            )
            if resolution.has_key and resolution.api_key:
                model_name = str(embeddings_model_entry.get("model") or spec.default_model)
                logger.debug(
                    "Using remote embeddings: provider=%s model=%s", byok_provider, model_name
                )
                return RemoteEmbeddingBackend(spec, resolution.api_key, model_name)

    local_model = settings.embedding_model_local or DEFAULT_LOCAL_EMBEDDING_MODEL
    return LocalEmbeddingBackend(local_model)
