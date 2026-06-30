"use client";

type Props = {
  url: string;
  title: string;
  domain: string;
};

function WebSearchChipIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width={12}
      height={12}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </svg>
  );
}

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
        <WebSearchChipIcon />
      </span>
      <span className="chat-citation-chip-label">{display}</span>
    </a>
  );
}
