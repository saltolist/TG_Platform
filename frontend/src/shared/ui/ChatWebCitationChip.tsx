"use client";

import { SearchIcon } from "@/shared/ui/model-picker";

type Props = {
  url: string;
  title: string;
  domain: string;
};

/** Inline web source chip at the end of an AI reply paragraph. */
export default function ChatWebCitationChip({ url, title, domain }: Props) {
  const display = (domain || title).trim() || "Источник";
  const fullTitle = title.trim() || display;
  return (
    <a
      href={url}
      className="chat-citation-chip chat-citation-chip--web"
      title={fullTitle}
      aria-label={`Источник: ${fullTitle}`}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="chat-citation-chip-icon" aria-hidden="true">
        <SearchIcon />
      </span>
      <span className="chat-citation-chip-label">{display}</span>
    </a>
  );
}
