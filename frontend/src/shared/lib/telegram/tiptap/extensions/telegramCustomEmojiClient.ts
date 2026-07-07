"use client";

import { ReactNodeViewRenderer } from "@tiptap/react";

import { TelegramCustomEmojiNodeView } from "../TelegramCustomEmojiNodeView";
import { TelegramCustomEmoji } from "./telegramCustomEmoji";

export const TelegramCustomEmojiWithPreview = TelegramCustomEmoji.extend({
  addNodeView() {
    return ReactNodeViewRenderer(TelegramCustomEmojiNodeView, {
      as: "span",
    });
  },
});
