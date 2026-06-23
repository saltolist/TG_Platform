"use client";

import Link from "next/link";

type Props = {
  href: string;
  label: string;
  title?: string;
};

/** Footnote-style citation chip — references source, not part of sentence text. */
export default function ChatCitationChip({ href, label, title }: Props) {
  const display = label.trim() || "Заметка";
  const fullTitle = title?.trim() || display;
  const tooltip = fullTitle !== display ? fullTitle : "Источник: заметка";
  return (
    <Link
      href={href}
      className="chat-citation-chip"
      title={tooltip}
      aria-label={`Источник: ${fullTitle}`}
    >
      {display}
    </Link>
  );
}
