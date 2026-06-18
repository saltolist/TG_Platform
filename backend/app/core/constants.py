"""Shared account identifiers (mirror frontend auth constants)."""

# Legacy shared guest token (kept for smoke scripts and older clients).
PRESENTATION_GUEST_TOKEN = "presentation:guest"

# Per-browser anonymous session: guest:<uuid>
GUEST_TOKEN_PREFIX = "guest:"

# Internal seed account — not used for login.
PRESENTATION_EMAIL = "presentation@example.com"
LEGACY_PRESENTATION_EMAIL = "prezentaciya@mail.ru"
DEMO_EMAIL = "demo@mail.ru"
