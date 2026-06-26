import { routes } from "@/shared/lib/routes";

const MAX_CHIP_LABEL_LEN = 22;

export const NOTE_CITE_LINK_RE =
  /\s*\[([^\]]+)\]\((\/note\/[^)]+|note:(?:global|post)\/[^)]+)\)/g;

export type NoteCitationSegment =
  | { type: "text"; text: string }
  | { type: "cite"; title: string; href: string };

/** True if href points to a note page (internal citation target). */
export function isNoteCitationHref(href: string): boolean {
  if (href.startsWith("/note/")) return true;
  if (href.startsWith("note:global/") || href.startsWith("note:post/")) return true;
  return false;
}

/** Resolve note citation href to an app route. */
export function resolveNoteCitationHref(href: string): string | null {
  if (href.startsWith("/note/")) {
    return href.endsWith("/") ? href : `${href}/`;
  }
  if (href.startsWith("note:global/")) {
    const id = decodeURIComponent(href.slice("note:global/".length));
    if (!id) return null;
    return routes.noteGlobal(id);
  }
  if (href.startsWith("note:post/")) {
    const rest = href.slice("note:post/".length);
    const slash = rest.indexOf("/");
    if (slash < 0) return null;
    const postId = decodeURIComponent(rest.slice(0, slash));
    const noteId = decodeURIComponent(rest.slice(slash + 1));
    if (!postId || !noteId) return null;
    return routes.notePost(postId, noteId);
  }
  return null;
}

/** Truncate long note titles for inline chip display. */
export function citationChipLabel(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "Заметка";
  if (trimmed.length <= MAX_CHIP_LABEL_LEN) return trimmed;
  return `${trimmed.slice(0, MAX_CHIP_LABEL_LEN - 1)}…`;
}

/** Fix common LLM citation formats before markdown parsing. */
export function normalizeNoteCitationMarkdown(text: string): string {
  let out = text;

  out = out.replace(
    /\[([^\]]+)\]\(\s*cite-path:\s*(\/note\/[^)\s]+)\s*\)/gi,
    "[$1]($2)",
  );

  out = out.replace(
    /cite-path:\s*(\/note\/\S+?)\s+cite-title:\s*([^\n\[\]]+?)(?=\s*(?:\n|---|$))/gi,
    (_match, path: string, title: string) => `[${title.trim()}](${path})`,
  );

  return out;
}

function detachCitationsInParagraph(paragraph: string): string {
  const cites: string[] = [];
  const body = paragraph
    .replace(NOTE_CITE_LINK_RE, (_match, title: string, href: string) => {
      cites.push(`[${title}](${href})`);
      return " ";
    })
    .replace(/[ \t]+/g, " ")
    .replace(/\n+/g, " ")
    .trim();

  if (!cites.length) return paragraph.trim();

  return `${body} ${cites.join(" ")}`.replace(/\s+/g, " ").trim();
}

/**
 * Pull note citation links out of paragraph text and append them at the paragraph end.
 * "В [Работа](/note/…) заметке …" → "В заметке сказано. [Работа](/note/…)"
 */
export function detachNoteCitations(text: string): string {
  NOTE_CITE_LINK_RE.lastIndex = 0;
  if (!NOTE_CITE_LINK_RE.test(text)) return text;
  NOTE_CITE_LINK_RE.lastIndex = 0;

  const chunks = text.split(/(\n{2,})/);
  return chunks
    .map((chunk) => {
      if (/^\n+$/.test(chunk)) return chunk;
      return detachCitationsInParagraph(chunk);
    })
    .join("");
}

export function prepareNoteCitationsForDisplay(text: string): string {
  return detachNoteCitations(normalizeNoteCitationMarkdown(text));
}

export function splitNoteCitationSegments(text: string): NoteCitationSegment[] {
  const segments: NoteCitationSegment[] = [];
  const re = new RegExp(NOTE_CITE_LINK_RE.source, "g");
  let last = 0;

  for (const match of text.matchAll(re)) {
    const index = match.index ?? 0;
    if (index > last) {
      segments.push({ type: "text", text: text.slice(last, index) });
    }
    segments.push({ type: "cite", title: match[1], href: match[2] });
    last = index + match[0].length;
  }

  if (last < text.length) {
    segments.push({ type: "text", text: text.slice(last) });
  }

  return segments;
}
