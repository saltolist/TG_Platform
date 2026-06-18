import { DEMO_EMAIL } from "@/shared/lib/auth/constants";
import { getGuestOverlayKey } from "@/shared/lib/auth/queryAccountScope";
import { isGuestBrowsing, readSession } from "@/shared/lib/auth/session";

export function getOverlayAccountKey(): string {
  const session = readSession();
  if (session?.accountId) return session.accountId;

  const guestKey = getGuestOverlayKey();
  if (guestKey) return guestKey;

  return "presentation";
}

export function isOverlayAccount(accountId = getOverlayAccountKey()): boolean {
  if (isGuestBrowsing()) return true;
  const session = readSession();
  return session?.email?.toLowerCase() === DEMO_EMAIL;
}
