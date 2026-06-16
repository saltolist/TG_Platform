import { DEMO_EMAIL, PRESENTATION_ACCOUNT_ID } from "@/shared/lib/auth/constants";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import { readSession } from "@/shared/lib/auth/session";

export function getOverlayAccountKey(): string {
  return getQueryAccountIdFromAuth();
}

export function isOverlayAccount(accountId = getOverlayAccountKey()): boolean {
  if (accountId === PRESENTATION_ACCOUNT_ID) return true;
  const session = readSession();
  return session?.email?.toLowerCase() === DEMO_EMAIL;
}
