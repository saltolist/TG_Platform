import { describe, expect, it, beforeEach } from "vitest";

import {
  createAuthToken,
  createFreshAccount,
  getStoreForRequest,
  resetAccountRegistry,
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
});
