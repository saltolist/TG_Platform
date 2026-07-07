"use client";

import { CustomEmojiCaretStruts } from "./extensions/customEmojiCaretStruts";
import { CustomEmojiMarkNavigation } from "./extensions/customEmojiMarkNavigation";
import { TelegramCustomEmojiWithPreview } from "./extensions/telegramCustomEmojiClient";
import { getTelegramPostExtensions } from "./telegramExtensions";

export function getTelegramPostEditorExtensions(placeholder?: string) {
  const extensions = getTelegramPostExtensions({ placeholder });
  return [
    ...extensions.map((extension) =>
      extension.name === "telegramCustomEmoji" ? TelegramCustomEmojiWithPreview : extension,
    ),
    CustomEmojiMarkNavigation,
    CustomEmojiCaretStruts,
  ];
}
