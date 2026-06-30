import { describe, expect, it } from "vitest";

import {
  citationChipLabel,
  detachNoteCitations,
  isNoteCitationHref,
  normalizeNoteCitationMarkdown,
  resolveNoteCitationChipLabel,
  resolveNoteCitationHref,
  rewriteNoteCitationLinkTitles,
  splitNoteCitationSegments,
  stripInvalidNoteCitations,
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

describe("stripInvalidNoteCitations", () => {
  it("keeps citations that point to known notes", () => {
    const valid = new Set(["/note/global/1/"]);
    expect(
      stripInvalidNoteCitations("Факт.[Работа](/note/global/1/)", valid),
    ).toBe("Факт.[Работа](/note/global/1/)");
  });

  it("removes citations to unknown notes", () => {
    const valid = new Set(["/note/global/1/"]);
    expect(
      stripInvalidNoteCitations(
        "Факт.[Работа](/note/global/1/) Выдумка.[X](/note/global/999/)",
        valid,
      ),
    ).toBe("Факт.[Работа](/note/global/1/) Выдумка.");
  });

  it("removes all citations when valid set is empty", () => {
    expect(stripInvalidNoteCitations("Текст.[A](/note/global/1/)", new Set())).toBe("Текст.");
  });
});

describe("rewriteNoteCitationLinkTitles", () => {
  it("replaces wrong LLM link label with canonical note title", () => {
    const titles = new Map([["/note/global/1/", "Серия постов"]]);
    expect(
      rewriteNoteCitationLinkTitles(
        "Судя по вашей заметке [Вижу](/note/global/1/), вы запланировали три публикации.",
        titles,
      ),
    ).toBe(
      "Судя по вашей заметке [Серия постов](/note/global/1/), вы запланировали три публикации.",
    );
  });
});

describe("resolveNoteCitationChipLabel", () => {
  it("prefers canonical title from map over link text", () => {
    const titles = new Map([["/note/global/1/", "Серия постов"]]);
    expect(resolveNoteCitationChipLabel("/note/global/1/", "Вижу", titles)).toEqual({
      label: "Серия постов",
      fullTitle: "Серия постов",
    });
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
