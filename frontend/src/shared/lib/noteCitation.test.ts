import { describe, expect, it } from "vitest";

import {
  citationChipLabel,
  isNoteCitationHref,
  resolveNoteCitationHref,
} from "./noteCitation";

describe("resolveNoteCitationHref", () => {
  it("resolves path-based global note citation", () => {
    expect(resolveNoteCitationHref("/note/global/gn1/")).toBe("/note/global/gn1/");
    expect(resolveNoteCitationHref("/note/global/gn1")).toBe("/note/global/gn1/");
  });

  it("resolves path-based post note citation", () => {
    expect(resolveNoteCitationHref("/note/post/p5/n7/")).toBe("/note/post/p5/n7/");
  });

  it("resolves legacy note: protocol citations", () => {
    expect(resolveNoteCitationHref("note:global/gn1")).toBe("/note/global/gn1/");
    expect(resolveNoteCitationHref("note:post/p5/n7")).toBe("/note/post/p5/n7/");
  });

  it("returns null for unknown scheme", () => {
    expect(resolveNoteCitationHref("https://example.com")).toBeNull();
    expect(resolveNoteCitationHref("note:unknown/x")).toBeNull();
  });
});

describe("isNoteCitationHref", () => {
  it("detects note paths and legacy protocol", () => {
    expect(isNoteCitationHref("/note/global/x/")).toBe(true);
    expect(isNoteCitationHref("note:global/x")).toBe(true);
    expect(isNoteCitationHref("https://example.com")).toBe(false);
  });
});

describe("citationChipLabel", () => {
  it("uses note title as chip label", () => {
    expect(citationChipLabel("Моя заметка")).toBe("Моя заметка");
    expect(citationChipLabel("  Работа  ")).toBe("Работа");
  });

  it("truncates very long titles", () => {
    const long = "А".repeat(30);
    expect(citationChipLabel(long)).toHaveLength(22);
    expect(citationChipLabel(long).endsWith("…")).toBe(true);
  });

  it("falls back for empty label", () => {
    expect(citationChipLabel("")).toBe("Заметка");
  });
});
