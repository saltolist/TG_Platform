"use client";

import { MarkViewContent, type MarkViewProps } from "@tiptap/react";

import { CustomEmojiPreview } from "@/shared/ui/CustomEmojiPreview";

export function TelegramCustomEmojiMarkView({ mark }: MarkViewProps) {
  const documentId = String(mark.attrs.documentId ?? "");

  return (
    <>
      <MarkViewContent as="span" className="telegram-emoji-glyph" />
      <span
        className="telegram-emoji-overlay"
        aria-hidden="true"
        contentEditable={false}
        data-emoji-id={documentId}
      >
        <CustomEmojiPreview
          documentId={documentId}
          alt="⭐"
          className="tg-custom-emoji telegram-emoji-node-preview"
        />
      </span>
    </>
  );
}
