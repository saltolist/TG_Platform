"use client";

import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";

import { CustomEmojiPreview } from "@/shared/ui/CustomEmojiPreview";

export function TelegramEmojiNodeView({ node }: NodeViewProps) {
  const documentId = String(node.attrs.documentId ?? "");
  const alt = String(node.attrs.alt ?? "⭐");

  return (
    <NodeViewWrapper
      as="span"
      className="telegram-emoji-node"
      contentEditable={false}
      data-emoji-id={documentId}
    >
      {/* Fallback alt char sets line/caret metrics like a normal emoji character. */}
      <span className="telegram-emoji-glyph" aria-hidden="true">
        {alt}
      </span>
      <span className="telegram-emoji-overlay">
        <CustomEmojiPreview
          documentId={documentId}
          alt={alt}
          className="tg-custom-emoji telegram-emoji-node-preview"
        />
      </span>
    </NodeViewWrapper>
  );
}
