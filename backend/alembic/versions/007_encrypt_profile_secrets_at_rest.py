"""encrypt remaining profile secrets at rest (AI + Telegram)

Revision ID: 007_encrypt_profile_secrets
Revises: 006_encrypt_byok_keys
Create Date: 2026-06-24

006 only walked ``llmModels``, ``webSearchModels``, ``orchestratorModels`` and
``embeddingsModel``.  Application code also encrypts ``visionModels``,
``imageGenerationModels``, ``webReasonerModels``, ``ragReasonerModels``, and
Telegram fields ``apiHash`` / ``botApiToken`` / ``sessionString``.

This migration reuses the same helpers as runtime (``encrypt_profile_keys``,
``encrypt_telegram_secrets``) with ``previous_profile`` set to the stored row so
that any still-plaintext values are opportunistically encrypted.

Safe to run multiple times:
- Already-encrypted values (``enc:v1:``) are skipped.
- ``env:<NAME>`` references and demo-fixture keys are skipped.
- If ``BYOK_ENCRYPTION_KEY`` is not set the migration is a no-op.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_encrypt_profile_secrets"
down_revision: Union[str, None] = "006_encrypt_byok_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)


def _parse_json_column(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def upgrade() -> None:
    key = os.environ.get("BYOK_ENCRYPTION_KEY", "").strip()
    if not key:
        logger.warning(
            "BYOK_ENCRYPTION_KEY not set — skipping 007 profile-secrets migration. "
            "Run again after setting BYOK_ENCRYPTION_KEY."
        )
        return

    from app.core.config import Settings
    from app.services.ai.byok_profile import encrypt_profile_keys
    from app.services.telegram.byok_telegram import encrypt_telegram_secrets

    settings = Settings(byok_encryption_key=key)
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT user_id, ai, telegram FROM profiles "
            "WHERE ai IS NOT NULL OR telegram IS NOT NULL"
        )
    ).fetchall()

    ai_updated = 0
    tg_updated = 0

    for user_id, raw_ai, raw_telegram in rows:
        ai = _parse_json_column(raw_ai)
        telegram = _parse_json_column(raw_telegram)

        if ai is not None:
            encrypted_ai = encrypt_profile_keys(ai, settings, previous_profile=ai)
            if json.dumps(encrypted_ai, sort_keys=True) != json.dumps(ai, sort_keys=True):
                conn.execute(
                    sa.text("UPDATE profiles SET ai = :ai WHERE user_id = :uid"),
                    {"ai": json.dumps(encrypted_ai), "uid": user_id},
                )
                ai_updated += 1

        if telegram is not None:
            encrypted_tg = encrypt_telegram_secrets(
                telegram, settings, previous_profile=telegram
            )
            if json.dumps(encrypted_tg, sort_keys=True) != json.dumps(
                telegram, sort_keys=True
            ):
                conn.execute(
                    sa.text("UPDATE profiles SET telegram = :tg WHERE user_id = :uid"),
                    {"tg": json.dumps(encrypted_tg), "uid": user_id},
                )
                tg_updated += 1

    logger.info(
        "007_encrypt_profile_secrets: encrypted AI keys in %d profile(s), "
        "Telegram secrets in %d profile(s)",
        ai_updated,
        tg_updated,
    )


def downgrade() -> None:
    logger.warning(
        "007_encrypt_profile_secrets downgrade: encrypted values remain in DB. "
        "Restore from backup if plaintext is needed."
    )
