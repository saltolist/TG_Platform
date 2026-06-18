import { PRESENTATION_ACCOUNT_ID, PRESENTATION_GUEST_TOKEN } from "@/shared/lib/auth/constants";
import { readGuestSession } from "@/shared/lib/auth/guestSession";
import {
  getApiAuthToken,
  isGuestBrowsing,
  isPresentationGuestApiToken,
  readSession,
} from "@/shared/lib/auth/session";

/** Shared seed tenant for API reads (presentation catalog). */
export function getQueryAccountIdFromAuth(): string {
  const session = readSession();
  if (session?.accountId) return session.accountId;

  const token = getApiAuthToken();
  if (token && isPresentationGuestApiToken(token)) return PRESENTATION_ACCOUNT_ID;
  if (!token || token === PRESENTATION_GUEST_TOKEN) return PRESENTATION_ACCOUNT_ID;

  const legacyAccountId = token.split(":")[0];
  if (legacyAccountId && legacyAccountId !== token) return legacyAccountId;
  return PRESENTATION_ACCOUNT_ID;
}

export function isPresentationAccount(accountId = getQueryAccountIdFromAuth()): boolean {
  if (isGuestBrowsing()) return true;
  return accountId === PRESENTATION_ACCOUNT_ID;
}

export function getGuestOverlayKey(): string | null {
  const guest = readGuestSession();
  if (!guest) return null;
  return guest.token;
}
