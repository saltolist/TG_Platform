import { GUEST_TOKEN_PREFIX } from "@/shared/lib/auth/constants";

export const GUEST_SESSION_STORAGE_KEY = "tg-platform-guest-session";

export type GuestSession = {
  guestId: string;
  token: string;
  createdAt: string;
};

function createGuestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `guest-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function buildGuestToken(guestId: string): string {
  return `${GUEST_TOKEN_PREFIX}${guestId}`;
}

export function isGuestToken(token: string): boolean {
  if (token.startsWith(GUEST_TOKEN_PREFIX)) {
    const guestId = token.slice(GUEST_TOKEN_PREFIX.length);
    return guestId.length > 0;
  }
  return false;
}

export function readGuestSession(): GuestSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(GUEST_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GuestSession;
    if (!parsed?.guestId || !parsed?.token || parsed.token !== buildGuestToken(parsed.guestId)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeGuestSession(session: GuestSession): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(GUEST_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearGuestSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(GUEST_SESSION_STORAGE_KEY);
}

/** Create or return the per-browser guest session (ChatGPT-style anonymous browsing). */
export function ensureGuestSession(): GuestSession {
  const existing = readGuestSession();
  if (existing) return existing;

  const guestId = createGuestId();
  const session: GuestSession = {
    guestId,
    token: buildGuestToken(guestId),
    createdAt: new Date().toISOString(),
  };
  writeGuestSession(session);
  return session;
}

export function rotateGuestSession(): GuestSession {
  clearGuestSession();
  return ensureGuestSession();
}
