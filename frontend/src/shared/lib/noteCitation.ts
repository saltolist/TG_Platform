import { routes } from "@/shared/lib/routes";

const MAX_CHIP_LABEL_LEN = 22;

export const NOTE_CITE_LINK_RE =
  /\s*\[([^\]]+)\]\((\/note\/[^)]+|note:(?:global|post)\/[^)]+)\)/g;

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

function detachCitationsInSentence(sentence: string): string {
  const cites: string[] = [];
  const body = sentence
    .replace(NOTE_CITE_LINK_RE, (_match, title: string, href: string) => {
      cites.push(`[${title}](${href})`);
      return " ";
    })
    .replace(/\s+/g, " ")
    .trim();

  if (!cites.length) return sentence.trim();

  const endPunct = body.match(/[.!?…]$/)?.[0] ?? "";
  const core = endPunct ? body.slice(0, -1).trimEnd() : body;
  return `${core}${endPunct}${cites.join("")}`;
}

/**
 * Pull note citation links out of sentence grammar and append them as trailing refs.
 * "В [Работа](/note/…) заметке …" → "В заметке …[Работа](/note/…)"
 */
export function detachNoteCitations(text: string): string {
  NOTE_CITE_LINK_RE.lastIndex = 0;
  if (!NOTE_CITE_LINK_RE.test(text)) return text;
  NOTE_CITE_LINK_RE.lastIndex = 0;

  const chunks = text.split(/(\n{2,})/);
  return chunks
    .map((chunk) => {
      if (/^\n+$/.test(chunk)) return chunk;
      return chunk
        .split(/(?<=[.!?…])\s+/)
        .map((sentence) => detachCitationsInSentence(sentence))
        .join(" ");
    })
    .join("");
}
