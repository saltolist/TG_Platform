import { DEMO_EMAIL } from "@/shared/lib/auth/constants";
import { getGuestOverlayKey } from "@/shared/lib/auth/queryAccountScope";
import { readSession } from "@/shared/lib/auth/session";
import { ensureDemoSession } from "@/shared/lib/overlay/demoSession";

/** Per-visitor tenant key sent to the API (guest:uuid or demo:uuid). */
export function getTenantSessionKey(): string | null {
  const guestKey = getGuestOverlayKey();
  if (guestKey) return guestKey;

  const session = readSession();
  if (session?.email?.toLowerCase() === DEMO_EMAIL) {
    return ensureDemoSession().key;
  }

  return null;
}
