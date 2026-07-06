"use client";

import { resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

function fileLabel(name: string, mime: string): string {
  const trimmed = name.trim();
  const dot = trimmed.lastIndexOf(".");
  if (dot > 0 && dot < trimmed.length - 1) {
    return trimmed.slice(dot + 1).toUpperCase().slice(0, 6);
  }
  const mimePart = mime.split("/").pop()?.trim();
  if (mimePart && mimePart !== "octet-stream") {
    return mimePart.toUpperCase().slice(0, 6);
  }
  return "ФАЙЛ";
}

export function DocumentMedia({ media }: Props) {
  const src = resolveMediaUrl(media.url);
  if (!src) return null;

  const name = media.name?.trim() || "Файл";
  const label = fileLabel(name, media.type || "");

  return (
    <a
      href={src}
      target="_blank"
      rel="noopener noreferrer"
      className="tg-media-file"
      title={`Открыть «${name}» в новой вкладке`}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <span className="tg-media-file-icon" aria-hidden>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 3H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9z" />
          <path d="M14 3v6h6" />
        </svg>
      </span>
      <span className="tg-media-file-name">{name}</span>
      <span className="tg-media-file-label">{label}</span>
    </a>
  );
}
