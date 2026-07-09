"""Pre-load the local fastembed model so RAG retrieval works without runtime downloads."""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("warmup_embeddings")


def main() -> int:
    model_name = (
        os.environ.get("EMBEDDING_MODEL_LOCAL", "").strip()
        or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    cache_path = os.environ.get("FASTEMBED_CACHE_PATH", "").strip() or "/app/.cache/fastembed"
    os.environ.setdefault("FASTEMBED_CACHE_PATH", cache_path)

    try:
        from fastembed import TextEmbedding

        TextEmbedding(model_name=model_name)
    except Exception as exc:
        logger.error(
            "Failed to load embedding model %r (cache=%s): %s",
            model_name,
            cache_path,
            exc,
        )
        return 1

    logger.info("Embedding model ready: %s (cache=%s)", model_name, cache_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
