import type { AuthSession } from "@/shared/lib/auth/types";
import { API_MODE } from "@/shared/config/dataSource";
import { AUTH_SESSION_STORAGE_KEY, PRESENTATION_GUEST_TOKEN } from "@/shared/lib/auth/constants";
import {
  ensureGuestSession,
  isGuestToken,
  readGuestSession,
} from "@/shared/lib/auth/guestSession";

export { AUTH_SESSION_STORAGE_KEY } from "@/shared/lib/auth/constants";

function hasSessionIdentity(session: AuthSession | null | undefined): session is AuthSession {
  return Boolean(session?.accountId && session?.email);
}

function sessionForStorage(session: AuthSession): AuthSession {
  if (!API_MODE) return session;
  return {
    accountId: session.accountId,
    email: session.email,
    createdAt: session.createdAt,
  };
}

export function readSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthSession;
    if (!hasSessionIdentity(parsed)) return null;
    if (!API_MODE && !parsed.token) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeSession(session: AuthSession): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(sessionForStorage(session)));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}

export function getSessionToken(): string | null {
  return readSession()?.token ?? null;
}

export function isGuestBrowsing(): boolean {
  return !readSession() && !!readGuestSession();
}

/** Logged-in user token, or per-browser guest token for presentation mode. */
export function getApiAuthToken(): string | null {
  if (API_MODE) {
    if (readSession()) return null;
  } else {
    const sessionToken = getSessionToken();
    if (sessionToken) return sessionToken;
  }

  const guest = readGuestSession();
  if (guest) return guest.token;

  if (typeof window === "undefined") return null;

  return ensureGuestSession().token;
}

export function patchSession(patch: Partial<AuthSession>): AuthSession | null {
  const current = readSession();
  if (!current) return null;
  const next = { ...current, ...patch };
  writeSession(next);
  return next;
}

export function isPresentationGuestApiToken(token: string | null): boolean {
  if (!token) return false;
  return token === PRESENTATION_GUEST_TOKEN || isGuestToken(token);
}
