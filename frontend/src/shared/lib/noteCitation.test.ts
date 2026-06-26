import { describe, expect, it } from "vitest";

import {
  citationChipLabel,
  detachNoteCitations,
  isNoteCitationHref,
  normalizeNoteCitationMarkdown,
  resolveNoteCitationHref,
  splitNoteCitationSegments,
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

describe("detachNoteCitations", () => {
  it("moves embedded citation to sentence end", () => {
    expect(detachNoteCitations("В [Работа](/note/global/1/) заметке сказано.")).toBe(
      "В заметке сказано. [Работа](/note/global/1/)",
    );
  });

  it("keeps citation already at sentence end", () => {
    expect(detachNoteCitations("Нужно сделать X.[Работа](/note/global/1/)")).toBe(
      "Нужно сделать X. [Работа](/note/global/1/)",
    );
  });

  it("collects multiple citations at paragraph end", () => {
    expect(
      detachNoteCitations("Текст [A](/note/global/1/) и [B](/note/global/2/) здесь."),
    ).toBe("Текст и здесь. [A](/note/global/1/) [B](/note/global/2/)");
  });

  it("moves citations from multiple sentences to paragraph end", () => {
    expect(
      detachNoteCitations(
        "В [A](/note/global/1/) первом предложении. Во [B](/note/global/2/) втором.",
      ),
    ).toBe("В первом предложении. Во втором. [A](/note/global/1/) [B](/note/global/2/)");
  });
});

describe("normalizeNoteCitationMarkdown", () => {
  it("converts cite-path metadata to markdown links", () => {
    expect(
      normalizeNoteCitationMarkdown(
        "Ответ cite-path: /note/global/1/ cite-title: Работа\nдальше.",
      ),
    ).toBe("Ответ [Работа](/note/global/1/)\nдальше.");
  });
});

describe("splitNoteCitationSegments", () => {
  it("splits trailing citation from sentence text", () => {
    expect(splitNoteCitationSegments("Текст. [Работа](/note/global/1/)")).toEqual([
      { type: "text", text: "Текст." },
      { type: "cite", title: "Работа", href: "/note/global/1/" },
    ]);
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
