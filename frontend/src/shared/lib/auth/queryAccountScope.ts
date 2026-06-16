import { PRESENTATION_ACCOUNT_ID, PRESENTATION_GUEST_TOKEN } from "@/shared/lib/auth/constants";
import { getApiAuthToken, readSession } from "@/shared/lib/auth/session";

/** Active tenant id for React Query cache and overlay (session UUID in HTTP mode). */
export function getQueryAccountIdFromAuth(): string {
  const session = readSession();
  if (session?.accountId) return session.accountId;
  const token = getApiAuthToken();
  if (!token || token === PRESENTATION_GUEST_TOKEN) return PRESENTATION_ACCOUNT_ID;
  const legacyAccountId = token.split(":")[0];
  if (legacyAccountId && legacyAccountId !== token) return legacyAccountId;
  return PRESENTATION_ACCOUNT_ID;
}

export function isPresentationAccount(accountId = getQueryAccountIdFromAuth()): boolean {
  return accountId === PRESENTATION_ACCOUNT_ID;
}
