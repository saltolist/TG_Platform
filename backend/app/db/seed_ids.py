import uuid

# Stable namespace for deterministic UUIDs from MSW string ids.
SEED_ID_NAMESPACE = uuid.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")


def seed_entity_uuid(kind: str, seed_id: str) -> uuid.UUID:
    """Map a frontend seed string id to a stable Postgres UUID primary key."""
    return uuid.uuid5(SEED_ID_NAMESPACE, f"{kind}:{seed_id}")


def user_scoped_entity_uuid(user_id: uuid.UUID, kind: str, seed_id: str) -> uuid.UUID:
    """Per-user stable UUID for imported channel content (avoids cross-account PK clashes)."""
    return uuid.uuid5(SEED_ID_NAMESPACE, f"{user_id}:{kind}:{seed_id}")
