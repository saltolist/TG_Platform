import { EMBED_RE } from "@/shared/lib/noteEmbeds/types";

export type LineHighlightPart = { type: "text" | "embed"; value: string };

/** Разбить строку на текст и токены `[file]` для подсветки в edit. */
export function splitLineHighlightParts(line: string): LineHighlightPart[] {
  const parts: LineHighlightPart[] = [];
  let last = 0;
  const re = new RegExp(EMBED_RE.source, "g");

  for (const match of line.matchAll(re)) {
    const index = match.index ?? 0;
    if (index > last) {
      parts.push({ type: "text", value: line.slice(last, index) });
    }
    parts.push({ type: "embed", value: match[0] });
    last = index + match[0].length;
  }

  if (last < line.length) {
    parts.push({ type: "text", value: line.slice(last) });
  }

  return parts;
}
