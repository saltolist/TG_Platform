import type { EmojiCollection } from "./emojiCatalog";

export type EmojiCollectionNav = {
  collection: EmojiCollection | null;
  collectionIndex: number;
  totalCollections: number;
  canGoPrev: boolean;
  canGoNext: boolean;
};

export function getEmojiCollectionNav(
  collections: EmojiCollection[],
  collectionIndex: number,
): EmojiCollectionNav {
  const totalCollections = collections.length;
  const safeIndex = Math.max(0, Math.min(collectionIndex, Math.max(0, totalCollections - 1)));
  return {
    collection: collections[safeIndex] ?? null,
    collectionIndex: safeIndex,
    totalCollections,
    canGoPrev: safeIndex > 0,
    canGoNext: safeIndex < totalCollections - 1,
  };
}
