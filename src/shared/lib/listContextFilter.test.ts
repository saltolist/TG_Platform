import { describe, expect, it } from "vitest";

import {
  LIST_CONTEXT_FILTER_OPTIONS,
  buildListContextFilterTabs,
  listContextFilterLabel,
  matchesListContextFilter,
} from "./listContextFilter";

describe("listContextFilter", () => {
  it("has three filter options", () => {
    expect(LIST_CONTEXT_FILTER_OPTIONS).toEqual(["all", "ai", "noai"]);
  });

  it("labels differ for desktop vs mobile", () => {
    expect(listContextFilterLabel("ai", true)).toContain("ИИ");
    expect(listContextFilterLabel("ai", false)).toBe("В контексте");
  });

  it("matchesListContextFilter", () => {
    expect(matchesListContextFilter(true, "all")).toBe(true);
    expect(matchesListContextFilter(true, "ai")).toBe(true);
    expect(matchesListContextFilter(true, "noai")).toBe(false);
    expect(matchesListContextFilter(false, "noai")).toBe(true);
  });

  it("buildListContextFilterTabs", () => {
    const desktop = buildListContextFilterTabs(true);
    expect(desktop).toHaveLength(3);
    expect(desktop[1]?.label).toContain("ИИ");
    const mobile = buildListContextFilterTabs(false);
    expect(mobile[1]?.label).toBe("В контексте");
  });
});
