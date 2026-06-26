"""Shared account identifiers (mirror frontend auth constants)."""

# Legacy shared guest token (kept for smoke scripts and older clients).
PRESENTATION_GUEST_TOKEN = "presentation:guest"

# Per-browser anonymous session: guest:<uuid>
GUEST_TOKEN_PREFIX = "guest:"

# Per-browser demo overlay session: demo:<uuid> (sent via X-Tenant-Session)
DEMO_TENANT_PREFIX = "demo:"

# Internal seed account — not used for login.
PRESENTATION_EMAIL = "presentation@example.com"
LEGACY_PRESENTATION_EMAIL = "prezentaciya@mail.ru"
DEMO_EMAIL = "demo@mail.ru"
DEMO_CHANNEL_TITLE = "Демо канал"

# Fixed verification code when SMTP is not configured (dev / Docker).
DEV_EMAIL_CODE = "000000"
