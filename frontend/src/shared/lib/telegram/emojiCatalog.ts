import { apiV1Path } from "@/shared/config/basePath";

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

/** Instant fallback when the Telegram catalog is still loading or unavailable. */
export const FALLBACK_EMOJI_CATALOG: EmojiCatalog = {
  collections: [
    {
      id: "unicode-fallback",
      title: "Смайлы",
      kind: "unicode",
      items: [
        "😀",
        "😃",
        "😄",
        "😁",
        "😆",
        "😅",
        "🤣",
        "😂",
        "🙂",
        "😉",
        "😊",
        "😇",
        "🥰",
        "😍",
        "🤩",
        "😘",
        "😗",
        "😚",
        "😙",
        "🥲",
        "😋",
        "😛",
        "😜",
        "🤪",
      ].map((char) => ({ type: "unicode" as const, char })),
    },
  ],
};

