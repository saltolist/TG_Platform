"use client";

import Link from "next/link";

import { NavIconNotes } from "@/shared/ui/nav-icons";

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
      <span className="chat-citation-chip-icon" aria-hidden="true">
        <NavIconNotes width={12} height={12} />
      </span>
      <span className="chat-citation-chip-label">{display}</span>
    </Link>
  );
}
