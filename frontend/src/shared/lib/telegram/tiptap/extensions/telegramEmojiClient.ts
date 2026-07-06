"use client";

import type { Extensions } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";

import { TelegramEmojiNodeView } from "../TelegramEmojiNodeView";
import { TelegramEmoji } from "./telegramEmoji";

export const TelegramEmojiWithPreview = TelegramEmoji.extend({
  addNodeView() {
    // ReactNodeViewRenderer crosses workspace package boundaries in types.
    return ReactNodeViewRenderer(TelegramEmojiNodeView) as never;
  },
});
