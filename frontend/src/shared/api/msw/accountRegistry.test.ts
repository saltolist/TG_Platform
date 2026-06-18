import { describe, expect, it, beforeEach } from "vitest";

import { PRESENTATION_ACCOUNT_ID } from "@/shared/lib/auth/constants";
import { buildGuestToken } from "@/shared/lib/auth/guestSession";
import {
  createAuthToken,
  createFreshAccount,
  getStoreForRequest,
  resetAccountRegistry,
  resolveAccountIdFromRequest,
} from "./accountRegistry";

function authRequest(token: string, method = "GET"): Request {
  return new Request("http://localhost/api/v1/profile/ai/", {
    method,
    headers: { Authorization: `Bearer ${token}` },
  });
}

describe("accountRegistry fresh accounts", () => {
  beforeEach(() => resetAccountRegistry());

  it("recreates empty fresh store after MSW registry reset (page reload)", () => {
    const accountId = createFreshAccount();
    const token = createAuthToken(accountId);

    resetAccountRegistry();

    const store = getStoreForRequest(authRequest(token));
    expect(store).not.toBeNull();
    expect(store!.aiProfile.llmModels).toEqual([]);
    expect(store!.posts).toEqual([]);
  });

  it("rejects unknown non-fresh account ids", () => {
    const store = getStoreForRequest(authRequest("unknown-user:token"));
    expect(store).toBeNull();
  });

  it("maps guest uuid tokens to the presentation account", () => {
    const guestToken = buildGuestToken("550e8400-e29b-41d4-a716-446655440000");
    expect(resolveAccountIdFromRequest(authRequest(guestToken))).toBe(PRESENTATION_ACCOUNT_ID);
    expect(getStoreForRequest(authRequest(guestToken))).not.toBeNull();
  });
});
