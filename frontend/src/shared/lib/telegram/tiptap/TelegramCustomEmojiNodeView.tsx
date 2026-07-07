"use client";

import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";

import { CustomEmojiPreview } from "@/shared/ui/CustomEmojiPreview";

export function TelegramCustomEmojiNodeView({ node }: NodeViewProps) {
  const documentId = String(node.attrs.documentId ?? "");
  const alt = String(node.attrs.alt ?? "⭐");

  return (
    <NodeViewWrapper
      as="span"
      className="telegram-emoji-atom"
      contentEditable={false}
      data-emoji-id={documentId}
    >
      <CustomEmojiPreview
        documentId={documentId}
        alt={alt}
        className="tg-custom-emoji telegram-emoji-node-preview"
      />
    </NodeViewWrapper>
  );
}
