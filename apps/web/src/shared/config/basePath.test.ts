import { describe, expect, it } from "vitest";

import { apiV1MswPath, apiV1Path } from "./basePath";

describe("apiV1Path", () => {
  it("adds trailing slash", () => {
    expect(apiV1Path("auth/login")).toBe("/api/v1/auth/login/");
    expect(apiV1Path("posts")).toBe("/api/v1/posts/");
    expect(apiV1Path("posts/1")).toBe("/api/v1/posts/1/");
    expect(apiV1Path("posts/:id")).toBe("/api/v1/posts/:id/");
  });

  it("strips redundant slashes from subpath", () => {
    expect(apiV1Path("/auth/login/")).toBe("/api/v1/auth/login/");
  });
});

describe("apiV1MswPath", () => {
  it("prefixes wildcard for MSW handler matching", () => {
    expect(apiV1MswPath("auth/login")).toBe("*/api/v1/auth/login/");
    expect(apiV1MswPath("posts/:id")).toBe("*/api/v1/posts/:id/");
  });
});
