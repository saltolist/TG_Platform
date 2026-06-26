import { USE_MSW, API_MODE } from "@/shared/config/dataSource";
import { DEMO_EMAIL } from "@/shared/lib/auth/constants";
import { getGuestOverlayKey } from "@/shared/lib/auth/queryAccountScope";
import { isGuestBrowsing, readSession } from "@/shared/lib/auth/session";
import { ensureDemoSession } from "@/shared/lib/overlay/demoSession";

export function getOverlayAccountKey(): string {
  const guestKey = getGuestOverlayKey();
  if (guestKey) return guestKey;

  const session = readSession();
  if (session?.email?.toLowerCase() === DEMO_EMAIL) {
    return ensureDemoSession().key;
  }

  if (session?.accountId) return session.accountId;

  return "presentation";
}

export function isOverlayAccount(accountId = getOverlayAccountKey()): boolean {
  if (isGuestBrowsing()) return true;
  const session = readSession();
  return session?.email?.toLowerCase() === DEMO_EMAIL;
}

/** Demo/guest overlay, or MSW dev — persist writes in localStorage across reloads. */
export function shouldPersistLocally(): boolean {
  return isOverlayAccount() || USE_MSW;
}

/** Sync overlay notes to backend for per-visitor RAG (Docker / real API only). */
export function shouldSyncOverlayToBackend(): boolean {
  return API_MODE && isOverlayAccount();
}
