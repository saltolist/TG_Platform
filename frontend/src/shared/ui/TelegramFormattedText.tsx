"use client";

import { useLayoutEffect, useRef, type MouseEvent } from "react";

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
  const renderedHtmlRef = useRef("");
  const html = textHtml?.trim();

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container || !html) return;

    const displayHtml = renderTelegramHtmlForDisplay(html);
    if (renderedHtmlRef.current !== displayHtml) {
      container.innerHTML = displayHtml;
      renderedHtmlRef.current = displayHtml;
    }

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
