/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import {
  getEmojiCollectionNav,
  getEmojiItemsPage,
  EMOJI_GRID_PAGE_SIZE,
} from "./emojiPickerPaging";
import type { EmojiCollection } from "./emojiCatalog";

const collections: EmojiCollection[] = [
  {
    id: "a",
    title: "First",
    kind: "unicode",
    items: [{ type: "unicode", char: "😀" }],
  },
  {
    id: "b",
    title: "Second",
    kind: "unicode",
    items: [{ type: "unicode", char: "😁" }],
  },
];

describe("emojiPickerPaging", () => {
  it("navigates collections with edge arrows", () => {
    expect(getEmojiCollectionNav(collections, 0)).toMatchObject({
      canGoPrev: false,
      canGoNext: true,
      collectionIndex: 0,
    });
    expect(getEmojiCollectionNav(collections, 1)).toMatchObject({
      canGoPrev: true,
      canGoNext: false,
      collectionIndex: 1,
    });
  });

  it("pages items within a collection", () => {
    const items = Array.from({ length: EMOJI_GRID_PAGE_SIZE + 3 }, (_, index) => ({
      type: "unicode" as const,
      char: String.fromCodePoint(0x1f600 + index),
    }));
    const first = getEmojiItemsPage(items, 0);
    expect(first.items).toHaveLength(EMOJI_GRID_PAGE_SIZE);
    expect(first.canGoPrev).toBe(false);
    expect(first.canGoNext).toBe(true);

    const second = getEmojiItemsPage(items, 1);
    expect(second.items).toHaveLength(3);
    expect(second.canGoPrev).toBe(true);
    expect(second.canGoNext).toBe(false);
  });
});
