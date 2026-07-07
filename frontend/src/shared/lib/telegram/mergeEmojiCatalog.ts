import type { EmojiCatalogItem, EmojiCollection } from "./emojiCatalog";
import { STANDARD_UNICODE_COLLECTION_TITLE } from "./emojiCatalog";
import { STANDARD_UNICODE_EMOJI_COLLECTION } from "./standardUnicodeEmojis";

function isStandardUnicodeCollection(collection: EmojiCollection): boolean {
  return (
    collection.kind === "unicode" &&
    (collection.id === "standard" ||
      collection.id === "unicode-fallback" ||
      collection.title === "Смайлы" ||
      collection.title === STANDARD_UNICODE_COLLECTION_TITLE)
  );
}

function mergeStandardUnicodeItems(
  full: EmojiCollection,
  remote: EmojiCollection,
): EmojiCollection {
  const seen = new Set<string>();
  const items: EmojiCatalogItem[] = [];

  for (const item of full.items) {
    if (item.type !== "unicode" || seen.has(item.char)) continue;
    seen.add(item.char);
    items.push(item);
  }

  for (const item of remote.items) {
    if (item.type !== "unicode" || seen.has(item.char)) continue;
    seen.add(item.char);
    items.push(item);
  }

  return {
    ...STANDARD_UNICODE_EMOJI_COLLECTION,
    items,
  };
}

/** Keep the full standard unicode set when Telegram returns a smaller category list. */
export function resolveEmojiCatalogCollections(remoteCollections: EmojiCollection[]): EmojiCollection[] {
  if (remoteCollections.length === 0) {
    return [STANDARD_UNICODE_EMOJI_COLLECTION];
  }

  const remoteStandard = remoteCollections.find(isStandardUnicodeCollection);
  const customCollections = remoteCollections.filter((collection) => collection.kind === "custom");

  const standard = remoteStandard
    ? mergeStandardUnicodeItems(STANDARD_UNICODE_EMOJI_COLLECTION, remoteStandard)
    : STANDARD_UNICODE_EMOJI_COLLECTION;

  return [standard, ...customCollections];
}
