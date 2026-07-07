/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import { getEmojiCollectionNav } from "./emojiPickerPaging";
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
});
