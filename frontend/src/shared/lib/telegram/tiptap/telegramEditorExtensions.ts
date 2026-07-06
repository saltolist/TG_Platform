"use client";

import { TelegramEmojiWithPreview } from "./extensions/telegramEmojiClient";
import { getTelegramPostExtensions } from "./telegramExtensions";

export function getTelegramPostEditorExtensions(placeholder?: string) {
  const extensions = getTelegramPostExtensions({ placeholder });
  return extensions.map((extension) =>
    extension.name === "telegramEmoji" ? TelegramEmojiWithPreview : extension,
  );
}
