import { routes } from "@/shared/lib/routes";

const MAX_CHIP_LABEL_LEN = 22;

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
