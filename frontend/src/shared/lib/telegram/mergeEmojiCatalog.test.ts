/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import { resolveEmojiCatalogCollections } from "./mergeEmojiCatalog";
import { STANDARD_UNICODE_EMOJI_CHARS } from "./standardUnicodeEmojis";

describe("resolveEmojiCatalogCollections", () => {
  it("returns the full standard set while loading", () => {
    const collections = resolveEmojiCatalogCollections([]);
    expect(collections).toHaveLength(1);
    expect(collections[0]?.items).toHaveLength(STANDARD_UNICODE_EMOJI_CHARS.length);
  });

  it("expands a smaller Telegram standard collection and keeps custom sets", () => {
    const collections = resolveEmojiCatalogCollections([
      {
        id: "standard",
        title: "Стандартные",
        kind: "unicode",
        items: [{ type: "unicode", char: "😀" }],
      },
      {
        id: "custom-0",
        title: "Premium",
        kind: "custom",
        items: [{ type: "custom", documentId: "1", alt: "⭐" }],
      },
    ]);

    expect(collections).toHaveLength(2);
    expect(collections[0]?.items).toHaveLength(STANDARD_UNICODE_EMOJI_CHARS.length);
    expect(collections[1]?.kind).toBe("custom");
  });
});
