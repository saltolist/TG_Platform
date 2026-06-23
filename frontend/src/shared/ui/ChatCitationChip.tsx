"use client";

import Link from "next/link";

type Props = {
  href: string;
  label: string;
  title?: string;
};

/** Perplexity-style inline citation chip — clickable, opens the note. */
export default function ChatCitationChip({ href, label, title }: Props) {
  const display = label.trim() || "Заметка";
  const fullTitle = title?.trim() || display;
  const tooltip = fullTitle !== display ? fullTitle : "Открыть заметку";
  return (
    <Link
      href={href}
      className="chat-citation-chip"
      title={tooltip}
      aria-label={`Открыть заметку: ${fullTitle}`}
    >
      {display}
    </Link>
  );
}
