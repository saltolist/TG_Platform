"use client";

import { ReactMarkViewRenderer } from "@tiptap/react";

import { TelegramCustomEmojiMarkView } from "../TelegramCustomEmojiMarkView";
import { TelegramCustomEmoji } from "./telegramCustomEmoji";

export const TelegramCustomEmojiWithPreview = TelegramCustomEmoji.extend({
  addMarkView() {
    return ReactMarkViewRenderer(TelegramCustomEmojiMarkView, {
      as: "span",
      className: "telegram-emoji-mark",
    }) as never;
  },
});
