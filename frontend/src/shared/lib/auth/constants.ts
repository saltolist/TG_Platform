export const AUTH_SESSION_STORAGE_KEY = "tg-platform-auth-session";

export const DEMO_ACCOUNT_ID = "demo-full";

export const DEMO_EMAIL = "demo@mail.ru";
export const DEMO_PASSWORD = "Demo!2026";

/** Per-browser demo overlay session prefix (X-Tenant-Session / localStorage key). */
export const DEMO_TENANT_PREFIX = "demo:";

export const DEMO_CHANNEL_HANDLE = "@demochannel";
export const DEMO_CHANNEL_TITLE = "Демо канал";

/** @deprecated Use DEMO_CHANNEL_HANDLE */
export const DEMO_KANAL_HANDLE = DEMO_CHANNEL_HANDLE;
/** @deprecated Use DEMO_CHANNEL_TITLE */
export const DEMO_KANAL_TITLE = DEMO_CHANNEL_TITLE;

/** Stub verification code for MSW (register / forgot password). */
export const DEMO_EMAIL_CODE = "000000";

export const PRESENTATION_ACCOUNT_ID = "presentation";
/** Internal seed email — not exposed in UI, not used for login. */
export const PRESENTATION_EMAIL = "presentation@example.com";
export const PRESENTATION_CHANNEL_HANDLE = "@prezentaciya";
export const PRESENTATION_CHANNEL_TITLE = "Презентация";

/** Per-browser anonymous guest session token prefix (Bearer guest:<uuid>). */
export const GUEST_TOKEN_PREFIX = "guest:";

/** Legacy shared guest token — kept for older clients and smoke scripts. */
export const PRESENTATION_GUEST_TOKEN = "presentation:guest";
