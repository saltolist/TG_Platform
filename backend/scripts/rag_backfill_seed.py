#!/usr/bin/env python3
"""Enqueue RAG re-indexing for presentation and demo seed accounts.

Run from backend/ with the app venv active:
  python scripts/rag_backfill_seed.py

Requires RAG_ENABLED=1 and a running embedding worker (backend process).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.constants import DEMO_EMAIL, PRESENTATION_EMAIL
from app.db.models import User
from app.db.session import SessionLocal
from app.services.ai.rag_worker import enqueue_backfill


async def main() -> None:
    settings = get_settings()
    if not settings.rag_enabled:
        print("RAG_ENABLED is off — nothing enqueued.")
        return

    async with SessionLocal() as session:
        async with session.begin():
            for email in (PRESENTATION_EMAIL, DEMO_EMAIL):
                user = (
                    await session.execute(select(User).where(User.email == email))
                ).scalar_one_or_none()
                if user is None:
                    print(f"Skip {email}: user not found (run seed first)")
                    continue
                await enqueue_backfill(session, user.id)
                print(f"Enqueued RAG backfill for {email}")

    print("Done. Embedding worker processes jobs within ~5s if backend is running.")


if __name__ == "__main__":
    asyncio.run(main())
