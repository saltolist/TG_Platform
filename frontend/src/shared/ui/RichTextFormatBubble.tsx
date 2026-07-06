"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  getRichTextFormatMenuPage,
  type RichTextFormatMenuItem,
} from "@/shared/lib/telegram/richTextFormatMenu";
import type { RichTextFormatBubbleState } from "@/shared/lib/telegram/useRichTextFormatBubble";
import type { RichTextFormat } from "@/shared/lib/telegram/richTextFormat";

type Props = {
  bubble: RichTextFormatBubbleState;
  onFormat: (format: RichTextFormat) => void;
};

export function RichTextFormatBubble({ bubble, onFormat }: Props) {
  const [page, setPage] = useState(0);
  const menu = getRichTextFormatMenuPage(page);

  useEffect(() => {
    if (bubble.open) {
      setPage(0);
    }
  }, [bubble.open, bubble.left, bubble.top]);

  if (!bubble.open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="rich-text-format-bubble"
      style={{
        position: "fixed",
        top: bubble.top,
        left: bubble.left,
        transform: "translate(-50%, -100%)",
      }}
      role="toolbar"
      aria-label="Форматирование выделенного текста"
      onMouseDown={(event) => event.preventDefault()}
    >
      {menu.canGoPrev ? (
        <button
          type="button"
          className="rich-text-format-bubble-nav"
          aria-label="Предыдущие форматы"
          onMouseDown={(event) => {
            event.preventDefault();
            setPage((current) => Math.max(0, current - 1));
          }}
        >
          ‹
        </button>
      ) : null}

      <div className="rich-text-format-bubble-page" aria-live="polite">
        {menu.items.map((item: RichTextFormatMenuItem) => (
          <button
            key={item.format}
            type="button"
            className="rich-text-format-bubble-btn"
            onMouseDown={(event) => {
              event.preventDefault();
              onFormat(item.format);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {menu.canGoNext ? (
        <button
          type="button"
          className="rich-text-format-bubble-nav"
          aria-label="Следующие форматы"
          onMouseDown={(event) => {
            event.preventDefault();
            setPage((current) => {
              const { totalPages } = getRichTextFormatMenuPage(current);
              return Math.min(totalPages - 1, current + 1);
            });
          }}
        >
          ›
        </button>
      ) : null}
    </div>,
    document.body,
  );
}
