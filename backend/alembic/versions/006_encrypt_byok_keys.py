"""encrypt BYOK API keys at rest in profiles.ai

Revision ID: 006_encrypt_byok_keys
Revises: 005_pgvector_rag_tables
Create Date: 2026-06-23

Walks every row in the ``profiles`` table and, for each model entry in
``profiles.ai``, encrypts plaintext BYOK API keys with Fernet.

Safe to run multiple times:
- Values already prefixed with ``enc:v1:`` are skipped.
- ``env:<NAME>`` references and demo-fixture keys are skipped.
- If ``BYOK_ENCRYPTION_KEY`` is not set the migration is a no-op
  (logs a warning and exits cleanly).
"""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_encrypt_byok_keys"
down_revision: Union[str, None] = "005_pgvector_rag_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)

_ENV_REF_PREFIX = "env:"
_ENC_PREFIX = "enc:v1:"

_DEMO_FIXTURE_API_KEYS = frozenset(
    {
        "sk-openai-demo",
        "sk-anthropic-demo",
        "pk-perplexity-demo",
        "tvly-demo",
        "exa-demo",
    }
)

_LIST_FIELDS = ("llmModels", "webSearchModels", "orchestratorModels")
_SINGLE_FIELDS = ("embeddingsModel",)


def _should_encrypt(api_key: str) -> bool:
    if not api_key:
        return False
    if api_key.startswith(_ENV_REF_PREFIX):
        return False
    if api_key.startswith(_ENC_PREFIX):
        return False
    if api_key in _DEMO_FIXTURE_API_KEYS:
        return False
    return True


def _encrypt_profile(profile: dict[str, Any], fernet) -> tuple[dict[str, Any], int]:
    """Return (updated_profile, num_encrypted).  Modifies a deep copy."""
    result = copy.deepcopy(profile)
    count = 0

    for field in _LIST_FIELDS:
        for model in result.get(field) or []:
            raw = str(model.get("apiKey") or "")
            if _should_encrypt(raw):
                model["apiKey"] = _ENC_PREFIX + fernet.encrypt(raw.encode()).decode()
                count += 1

    for field in _SINGLE_FIELDS:
        model = result.get(field)
        if isinstance(model, dict):
            raw = str(model.get("apiKey") or "")
            if _should_encrypt(raw):
                model["apiKey"] = _ENC_PREFIX + fernet.encrypt(raw.encode()).decode()
                count += 1

    return result, count


def upgrade() -> None:
    key = os.environ.get("BYOK_ENCRYPTION_KEY", "").strip()
    if not key:
        logger.warning(
            "BYOK_ENCRYPTION_KEY not set — skipping BYOK key encryption migration. "
            "Run again after setting BYOK_ENCRYPTION_KEY to encrypt existing keys."
        )
        return

    try:
        from cryptography.fernet import Fernet

        fernet = Fernet(key.encode())
    except Exception as exc:  # noqa: BLE001
        logger.error("Invalid BYOK_ENCRYPTION_KEY: %s — aborting migration", exc)
        raise

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT user_id, ai FROM profiles WHERE ai IS NOT NULL")).fetchall()

    updated = 0
    total_keys = 0
    for row in rows:
        user_id = row[0]
        raw_ai = row[1]

        if isinstance(raw_ai, str):
            profile = json.loads(raw_ai)
        elif isinstance(raw_ai, dict):
            profile = raw_ai
        else:
            continue

        new_profile, count = _encrypt_profile(profile, fernet)
        if count == 0:
            continue

        conn.execute(
            sa.text("UPDATE profiles SET ai = :ai WHERE user_id = :uid"),
            {"ai": json.dumps(new_profile), "uid": user_id},
        )
        updated += 1
        total_keys += count

    logger.info(
        "006_encrypt_byok_keys: encrypted %d BYOK key(s) across %d profile(s)",
        total_keys,
        updated,
    )


def downgrade() -> None:
    # Decryption on downgrade is intentionally not implemented:
    # reverting encryption requires the Fernet key to be present and is
    # destructive if the key is lost. Operators should take a DB backup before
    # running this migration.
    logger.warning(
        "006_encrypt_byok_keys downgrade: BYOK keys remain encrypted in DB. "
        "Restore from backup if plaintext is needed."
    )
