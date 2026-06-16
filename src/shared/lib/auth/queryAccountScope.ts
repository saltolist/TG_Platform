import { PRESENTATION_ACCOUNT_ID } from "@/shared/lib/auth/constants";
import { getApiAuthToken } from "@/shared/lib/auth/session";

/** Active MSW tenant id from the current auth token (works outside React). */
export function getQueryAccountIdFromAuth(): string {
  const token = getApiAuthToken();
  const accountId = token?.split(":")[0];
  return accountId || PRESENTATION_ACCOUNT_ID;
}
