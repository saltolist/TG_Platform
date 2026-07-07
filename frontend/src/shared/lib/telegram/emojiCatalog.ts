export { emojiPreviewApiUrl, telegramEmojiPreviewUrl } from "@/shared/lib/telegram/emojiPreviewClient";

export type UnicodeEmojiItem = {
  type: "unicode";
  char: string;
};

export type CustomEmojiItem = {
  type: "custom";
  documentId: string;
  alt: string;
};

export type EmojiCatalogItem = UnicodeEmojiItem | CustomEmojiItem;

export type EmojiCollection = {
  id: string;
  title: string;
  kind: "unicode" | "custom";
  iconDocumentId?: string;
  items: EmojiCatalogItem[];
};

export type EmojiCatalog = {
  collections: EmojiCollection[];
};

import { STANDARD_UNICODE_EMOJI_COLLECTION } from "./standardUnicodeEmojis";

/** Instant fallback when the Telegram catalog is still loading or unavailable. */
export const FALLBACK_EMOJI_CATALOG: EmojiCatalog = {
  collections: [STANDARD_UNICODE_EMOJI_COLLECTION],
};

export const STANDARD_UNICODE_COLLECTION_TITLE = "Стандартные";

export function getEmojiCollectionTitle(collection: { id: string; title: string; kind: string }): string {
  if (
    collection.kind === "unicode" &&
    (collection.id === "standard" ||
      collection.id === "unicode-fallback" ||
      collection.title === "Смайлы")
  ) {
    return STANDARD_UNICODE_COLLECTION_TITLE;
  }
  return collection.title;
}
