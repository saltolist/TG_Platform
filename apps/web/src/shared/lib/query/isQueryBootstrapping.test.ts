import { describe, expect, it } from "vitest";

import {
  isListQueryBootstrapping,
  isQueryBootstrapping,
} from "./isQueryBootstrapping";

describe("isQueryBootstrapping", () => {
  it("is true only without cached data", () => {
    expect(isQueryBootstrapping(true, undefined)).toBe(true);
    expect(isQueryBootstrapping(true, { id: 1 })).toBe(false);
    expect(isQueryBootstrapping(false, undefined)).toBe(false);
  });
});

describe("isListQueryBootstrapping", () => {
  it("is true only for empty or missing lists", () => {
    expect(isListQueryBootstrapping(true, undefined)).toBe(true);
    expect(isListQueryBootstrapping(true, [])).toBe(true);
    expect(isListQueryBootstrapping(true, [{ id: 1 }])).toBe(false);
    expect(isListQueryBootstrapping(false, undefined)).toBe(false);
  });
});
