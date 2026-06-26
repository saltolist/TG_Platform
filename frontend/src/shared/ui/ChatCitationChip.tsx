"use client";

import Link from "next/link";

type Props = {
  href: string;
  label: string;
  title?: string;
};

/** Inline source chip at the end of an AI reply paragraph. */
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
