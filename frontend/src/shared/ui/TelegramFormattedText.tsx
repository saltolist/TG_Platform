"use client";

import type { MouseEvent } from "react";

import { sanitizeTelegramHtml } from "@/shared/lib/telegram/sanitizeTelegramHtml";

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
  const html = textHtml?.trim();
  if (html) {
    return (
      <div
        className={["tg-formatted-text", className].filter(Boolean).join(" ")}
        dangerouslySetInnerHTML={{ __html: sanitizeTelegramHtml(html) }}
        onClick={revealSpoiler}
      />
    );
  }
  if (!text) {
    return emptyClassName ? <div className={emptyClassName} /> : null;
  }
  return <div className={className}>{text}</div>;
}
