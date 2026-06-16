import type { AuthSession } from "@/shared/lib/auth/types";
import { AUTH_SESSION_STORAGE_KEY, PRESENTATION_GUEST_TOKEN } from "./constants";

export function readSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthSession;
    if (!parsed?.token || !parsed?.accountId || !parsed?.email) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeSession(session: AuthSession): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}

export function getSessionToken(): string | null {
  return readSession()?.token ?? null;
}

/** Session token, or presentation guest token when browsing without login. */
export function getApiAuthToken(): string | null {
  const sessionToken = getSessionToken();
  if (sessionToken) return sessionToken;
  if (typeof window === "undefined") return null;
  return PRESENTATION_GUEST_TOKEN;
}

export function patchSession(patch: Partial<AuthSession>): AuthSession | null {
  const current = readSession();
  if (!current) return null;
  const next = { ...current, ...patch };
  writeSession(next);
  return next;
}
