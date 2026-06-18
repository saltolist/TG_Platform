import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  GUEST_SESSION_STORAGE_KEY,
  buildGuestToken,
  clearGuestSession,
  ensureGuestSession,
  isGuestToken,
  readGuestSession,
  rotateGuestSession,
} from "@/shared/lib/auth/guestSession";

function createStorageMock(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => {
      data.delete(key);
    },
    setItem: (key, value) => {
      data.set(key, value);
    },
  };
}

describe("guestSession", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { localStorage: createStorageMock() });
    vi.stubGlobal("crypto", { randomUUID: () => "550e8400-e29b-41d4-a716-446655440000" });
  });

  it("creates a persistent per-browser guest session", () => {
    const first = ensureGuestSession();
    const second = ensureGuestSession();

    expect(first.guestId).toBe("550e8400-e29b-41d4-a716-446655440000");
    expect(first.token).toBe(buildGuestToken(first.guestId));
    expect(second.token).toBe(first.token);
    expect(window.localStorage.getItem(GUEST_SESSION_STORAGE_KEY)).toBeTruthy();
  });

  it("rotates guest session on demand", () => {
    ensureGuestSession();
    clearGuestSession();

    vi.stubGlobal("crypto", {
      randomUUID: () => "22222222-2222-4222-8222-222222222222",
    });

    const rotated = rotateGuestSession();
    expect(rotated.guestId).toBe("22222222-2222-4222-8222-222222222222");
    expect(rotated.token).toBe(buildGuestToken(rotated.guestId));
  });

  it("detects guest bearer tokens", () => {
    expect(isGuestToken("guest:550e8400-e29b-41d4-a716-446655440000")).toBe(true);
    expect(isGuestToken("presentation:guest")).toBe(false);
    expect(isGuestToken("guest:")).toBe(false);
  });

  it("clears invalid stored guest sessions", () => {
    window.localStorage.setItem(
      GUEST_SESSION_STORAGE_KEY,
      JSON.stringify({ guestId: "x", token: "guest:y", createdAt: "now" }),
    );
    clearGuestSession();
    expect(readGuestSession()).toBeNull();
  });
});
