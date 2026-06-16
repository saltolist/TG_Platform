import { describe, expect, it } from "vitest";

import { isFeedPath } from "./isFeedPath";

describe("isFeedPath", () => {
  it("matches feed route", () => {
    expect(isFeedPath("/feed")).toBe(true);
    expect(isFeedPath("/feed/")).toBe(true);
    expect(isFeedPath("/")).toBe(false);
    expect(isFeedPath("/notes/")).toBe(false);
  });
});
