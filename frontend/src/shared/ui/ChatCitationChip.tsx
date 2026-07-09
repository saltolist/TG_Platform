"use client";

import Link from "next/link";

import { isPostCitationHref } from "@/shared/lib/noteCitation";
import { NavIconFeed, NavIconNotes } from "@/shared/ui/nav-icons";

type Props = {
  href: string;
  label: string;
  title?: string;
};

/** Inline source chip at the end of an AI reply paragraph. */
export default function ChatCitationChip({ href, label, title }: Props) {
  const isPost = isPostCitationHref(href);
  const display = label.trim() || (isPost ? "Пост" : "Заметка");
  const fullTitle = title?.trim() || display;
  const tooltip = fullTitle !== display ? fullTitle : `Источник: ${isPost ? "пост" : "заметка"}`;
  return (
    <Link
      href={href}
      className="chat-citation-chip"
      title={tooltip}
      aria-label={`Источник: ${fullTitle}`}
    >
      <span className="chat-citation-chip-icon" aria-hidden="true">
        {isPost ? (
          <NavIconFeed width={12} height={12} outerStrokeWidth={1.5} strokeWidth={1.5} />
        ) : (
          <NavIconNotes width={12} height={12} />
        )}
      </span>
      <span className="chat-citation-chip-label">{display}</span>
    </Link>
  );
}
