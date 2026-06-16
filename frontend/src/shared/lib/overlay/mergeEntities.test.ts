import { describe, expect, it } from "vitest";

import { mergeEntityList } from "@/shared/lib/overlay/mergeEntities";

describe("mergeEntityList", () => {
  it("applies upserts and removals on top of base list", () => {
    const base = [
      { id: "1", title: "a" },
      { id: "2", title: "b" },
    ];
    const merged = mergeEntityList(
      base,
      {
        upserts: { "2": { id: "2", title: "patched" }, "3": { id: "3", title: "new" } },
        removedIds: ["1"],
      },
    );
    expect(merged.map((item) => item.id)).toEqual(["3", "2"]);
    expect(merged.find((item) => item.id === "2")?.title).toBe("patched");
  });

  it("respects explicit order when provided", () => {
    const merged = mergeEntityList(
      [
        { id: "1", v: 1 },
        { id: "2", v: 2 },
      ],
      { upserts: {}, removedIds: [] },
      ["2", "1"],
    );
    expect(merged.map((item) => item.id)).toEqual(["2", "1"]);
  });
});
