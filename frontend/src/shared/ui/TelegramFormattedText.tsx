"use client";

import { useEffect, useRef, type MouseEvent } from "react";

import { hydrateCustomEmojiInDom } from "@/shared/lib/telegram/hydrateCustomEmojiDom";
import { renderTelegramHtmlForDisplay } from "@/shared/lib/telegram/sanitizeTelegramHtml";

type Props = {
  text: string;
  textHtml?: string | null;
  className?: string;
  emptyClassName?: string;
};

function revealSpoiler(event: MouseEvent<HTMLDivElement>) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.classList.contains("tg-spoiler")) {
    target.classList.add("revealed");
  }
}

export function TelegramFormattedText({ text, textHtml, className, emptyClassName }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const html = textHtml?.trim();

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !html) return;
    container.innerHTML = renderTelegramHtmlForDisplay(html);
    return hydrateCustomEmojiInDom(container);
  }, [html]);

  if (html) {
    return (
      <div
        ref={containerRef}
        className={["tg-formatted-text", className].filter(Boolean).join(" ")}
        onClick={revealSpoiler}
      />
    );
  }
  if (!text) {
    return emptyClassName ? <div className={emptyClassName} /> : null;
  }
  return <div className={className}>{text}</div>;
}
