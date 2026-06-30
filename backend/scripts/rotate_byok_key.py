"""Re-encrypt all BYOK secrets in profiles.ai and profiles.telegram.

Usage
-----
1. Set BYOK_ENCRYPTION_KEY to the **new** Fernet key.
2. Set BYOK_ENCRYPTION_OLD_KEYS to the **old** key(s), comma-separated.
3. Run from the backend directory (with .venv activated or inside Docker):

       python scripts/rotate_byok_key.py [--dry-run]

   --dry-run  Print what would change without writing to the database.

4. Verify no errors in the output.
5. Remove the old keys from BYOK_ENCRYPTION_OLD_KEYS in your .env / secrets.

The script is idempotent: values already encrypted with the new primary key
are skipped (MultiFernet.rotate() re-encrypts only ciphertexts that were
produced by an older key in the rotation set).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports so the script can be run without the full app being importable
# in every environment.
# ---------------------------------------------------------------------------

sys.path.insert(0, ".")  # allow `python scripts/rotate_byok_key.py` from backend/


def _load_settings():
    from app.core.config import get_settings  # noqa: PLC0415

    return get_settings()


def _get_multi_fernet(settings):
    """Build a MultiFernet from primary + old keys (for decryption / rotation)."""
    primary_raw = (settings.byok_encryption_key or "").strip()
    if not primary_raw:
        raise SystemExit("BYOK_ENCRYPTION_KEY is not set — nothing to do.")

    from cryptography.fernet import Fernet, MultiFernet  # noqa: PLC0415

    old_keys = settings.byok_old_keys_list
    if not old_keys:
        logger.warning(
            "BYOK_ENCRYPTION_OLD_KEYS is empty — all values are assumed to be "
            "already encrypted with the current primary key.  Nothing to rotate."
        )

    keys = [primary_raw] + old_keys
    fernets = [Fernet(k.encode()) for k in keys]
    return MultiFernet(fernets)


def _rotate_value(multi, value: str, enc_prefix: str) -> tuple[str, bool]:
    """Return (new_value, changed).

    MultiFernet.rotate() re-encrypts with the first (primary) key if the
    value was encrypted with any other key in the set; returns the same
    token when it was already produced by the primary key.
    """
    if not value or not value.startswith(enc_prefix):
        return value, False

    payload = value[len(enc_prefix):]
    try:
        new_payload = multi.rotate(payload.encode()).decode()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to rotate value starting with %r…: %s", value[:20], exc)
        return value, False

    new_value = enc_prefix + new_payload
    changed = new_value != value
    return new_value, changed


def _rotate_ai_profile(multi, profile: dict[str, Any], enc_prefix: str) -> tuple[dict[str, Any], int]:
    """Walk all model-list and single-model fields and rotate enc:v1: values."""
    import copy  # noqa: PLC0415

    result = copy.deepcopy(profile)
    count = 0

    list_fields = (
        "llmModels",
        "webSearchModels",
        "orchestratorModels",
        "webReasonerModels",
        "ragReasonerModels",
        "visionModels",
        "imageGenerationModels",
    )
    single_fields = ("embeddingsModel",)

    for field in list_fields:
        for model in result.get(field) or []:
            raw = str(model.get("apiKey") or "")
            new_val, changed = _rotate_value(multi, raw, enc_prefix)
            if changed:
                model["apiKey"] = new_val
                count += 1

    for field in single_fields:
        model = result.get(field)
        if isinstance(model, dict):
            raw = str(model.get("apiKey") or "")
            new_val, changed = _rotate_value(multi, raw, enc_prefix)
            if changed:
                model["apiKey"] = new_val
                count += 1

    return result, count


def _rotate_telegram_profile(multi, profile: dict[str, Any], enc_prefix: str) -> tuple[dict[str, Any], int]:
    import copy  # noqa: PLC0415

    result = copy.deepcopy(profile)
    count = 0
    secret_fields = ("apiHash", "botApiToken", "sessionString")
    for field in secret_fields:
        raw = str(result.get(field) or "")
        new_val, changed = _rotate_value(multi, raw, enc_prefix)
        if changed:
            result[field] = new_val
            count += 1
    return result, count


async def _run(dry_run: bool) -> None:
    settings = _load_settings()
    multi = _get_multi_fernet(settings)

    from app.core.crypto import ENC_PREFIX  # noqa: PLC0415
    from app.db.models import Profile  # noqa: PLC0415

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_profiles = 0
    total_rotated_fields = 0

    async with async_session() as session:
        result = await session.execute(select(Profile))
        profiles = result.scalars().all()

        for profile in profiles:
            total_profiles += 1
            dirty = False

            if profile.ai:
                new_ai, ai_count = _rotate_ai_profile(multi, profile.ai, ENC_PREFIX)
                if ai_count:
                    logger.info(
                        "Profile %s — rotated %d AI key(s)", profile.user_id, ai_count
                    )
                    if not dry_run:
                        profile.ai = new_ai
                    total_rotated_fields += ai_count
                    dirty = True

            if profile.telegram:
                new_tg, tg_count = _rotate_telegram_profile(
                    multi, profile.telegram, ENC_PREFIX
                )
                if tg_count:
                    logger.info(
                        "Profile %s — rotated %d Telegram secret(s)",
                        profile.user_id,
                        tg_count,
                    )
                    if not dry_run:
                        profile.telegram = new_tg
                    total_rotated_fields += tg_count
                    dirty = True

            if dirty and not dry_run:
                session.add(profile)

        if not dry_run:
            await session.commit()

    await engine.dispose()

    logger.info(
        "Done. Checked %d profile(s), rotated %d field(s).%s",
        total_profiles,
        total_rotated_fields,
        " (DRY RUN — no changes written)" if dry_run else "",
    )

    if total_rotated_fields == 0:
        logger.info(
            "Nothing to rotate — all enc:v1: values are already encrypted "
            "with the current primary key (or there are no encrypted values)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be rotated without writing to the database.",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN mode — no changes will be written.")

    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()
