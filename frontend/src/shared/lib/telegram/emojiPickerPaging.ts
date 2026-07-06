import type { EmojiCatalogItem, EmojiCollection } from "./emojiCatalog";

export const EMOJI_GRID_PAGE_SIZE = 24;

export type EmojiCollectionNav = {
  collection: EmojiCollection | null;
  collectionIndex: number;
  totalCollections: number;
  canGoPrev: boolean;
  canGoNext: boolean;
};

export type EmojiItemsPage = {
  items: EmojiCatalogItem[];
  page: number;
  totalPages: number;
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

export function getEmojiItemsPage(
  items: EmojiCatalogItem[],
  page: number,
  pageSize = EMOJI_GRID_PAGE_SIZE,
): EmojiItemsPage {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.max(0, Math.min(page, totalPages - 1));
  const start = safePage * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    totalPages,
    canGoPrev: safePage > 0,
    canGoNext: safePage < totalPages - 1,
  };
}
