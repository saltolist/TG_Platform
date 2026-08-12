import { z } from "zod";

import { kbCiteSchema, type KbCite } from "@/shared/api/schemas/post";
import { routes } from "@/shared/lib/routes";

const MAX_CHIP_LABEL_LEN = 22;

export const NOTE_CITE_LINK_RE =
  /\s*\[([^\]]+)\]\((\/(?:note|post)\/[^)]+|note:(?:global|post)\/[^)]+)\)/g;

export type NoteCitationSegment =
  | { type: "text"; text: string }
  | { type: "cite"; title: string; href: string };

/** True if href points to a knowledge-base citation target (note or post). */
export function isNoteCitationHref(href: string): boolean {
  if (href.startsWith("/note/")) return true;
  if (href.startsWith("/post/")) return true;
  if (href.startsWith("note:global/") || href.startsWith("note:post/")) return true;
  return false;
}

export function isPostCitationHref(href: string): boolean {
  return href.startsWith("/post/");
}

/** Resolve citation href to an app route. */
export function resolveNoteCitationHref(href: string): string | null {
  if (href.startsWith("/post/")) {
    const id = decodeURIComponent(href.slice("/post/".length).replace(/\/$/, ""));
    if (!id) return null;
    return routes.post(id);
  }
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

/** Truncate long titles for inline chip display. */
export function citationChipLabel(text: string, fallback = "Источник"): string {
  const trimmed = text.trim();
  if (!trimmed) return fallback;
  if (trimmed.length <= MAX_CHIP_LABEL_LEN) return trimmed;
  return `${trimmed.slice(0, MAX_CHIP_LABEL_LEN - 1)}…`;
}

/** Fix common LLM citation formats before markdown parsing. */
export function normalizeNoteCitationMarkdown(text: string): string {
  let out = text;

  out = out.replace(
    /\[([^\]]+)\]\(\s*cite-path:\s*((?:\/note|\/post)\/[^)\s]+)\s*\)/gi,
    "[$1]($2)",
  );

  out = out.replace(
    /cite-path:\s*((?:\/note|\/post)\/\S+?)\s+cite-title:\s*([^\n\[\]]+?)(?=\s*(?:\n|---|$))/gi,
    (_match, path: string, title: string) => `[${title.trim()}](${path})`,
  );

  return out;
}

/** Canonical path for comparing citation targets. */
export function normalizeNoteCitationPath(href: string): string | null {
  const resolved = resolveNoteCitationHref(href);
  if (!resolved) return null;
  return resolved.endsWith("/") ? resolved : `${resolved}/`;
}

/** Remove citation links that do not point to known notes/posts. */
export function stripInvalidNoteCitations(text: string, validPaths: ReadonlySet<string>): string {
  if (validPaths.size === 0) {
    NOTE_CITE_LINK_RE.lastIndex = 0;
    return text.replace(NOTE_CITE_LINK_RE, "");
  }

  NOTE_CITE_LINK_RE.lastIndex = 0;
  return text.replace(NOTE_CITE_LINK_RE, (match, _title: string, href: string) => {
    const normalized = normalizeNoteCitationPath(href);
    if (normalized && validPaths.has(normalized)) return match;
    return "";
  });
}

/** Parse kb_cites from SSE meta without failing the whole meta block. */
export function parseKbCitesFromStreamMeta(meta: Record<string, unknown>): KbCite[] {
  const raw = meta.kb_cites;
  if (!Array.isArray(raw) || raw.length === 0) return [];
  const parsed = z.array(kbCiteSchema).safeParse(raw);
  return parsed.success ? parsed.data : [];
}

/** Build validation set from backend RAG cites (strict — only cited sources). */
export function buildValidPathsFromKbCites(kbCites: readonly KbCite[]): Set<string> {
  const paths = new Set<string>();
  for (const cite of kbCites) {
    const normalized = normalizeNoteCitationPath(cite.path);
    if (normalized) paths.add(normalized);
  }
  return paths;
}

/** Merge kb cite titles into the account-wide title map. */
export function mergeKbCiteTitles(
  titleByPath: ReadonlyMap<string, string>,
  kbCites: readonly KbCite[],
): Map<string, string> {
  const merged = new Map(titleByPath);
  for (const cite of kbCites) {
    const normalized = normalizeNoteCitationPath(cite.path);
    const title = cite.title.trim();
    if (normalized && title) merged.set(normalized, title);
  }
  return merged;
}

/** Remove citations to the post the user is already editing in post-scoped chat. */
export function stripSelfPostCitations(text: string, postIds: readonly string[]): string {
  if (!postIds.length) return text;
  const selfPaths = new Set<string>();
  for (const id of postIds) {
    const trimmed = id.trim();
    if (!trimmed) continue;
    const path = normalizeNoteCitationPath(routes.post(trimmed));
    if (path) selfPaths.add(path);
  }
  if (selfPaths.size === 0) return text;

  NOTE_CITE_LINK_RE.lastIndex = 0;
  return text.replace(NOTE_CITE_LINK_RE, (match, _title: string, href: string) => {
    const normalized = normalizeNoteCitationPath(href);
    if (normalized && selfPaths.has(normalized)) return "";
    return match;
  });
}

/** Replace wrong LLM link labels with canonical titles when path is known. */
export function rewriteNoteCitationLinkTitles(
  text: string,
  titleByPath: ReadonlyMap<string, string>,
): string {
  if (titleByPath.size === 0) return text;
  NOTE_CITE_LINK_RE.lastIndex = 0;
  return text.replace(NOTE_CITE_LINK_RE, (match, _title: string, href: string) => {
    const normalized = normalizeNoteCitationPath(href);
    if (!normalized) return match;
    const canonical = titleByPath.get(normalized);
    if (!canonical) return match;
    return ` [${canonical}](${href})`;
  });
}

export function resolveNoteCitationChipLabel(
  href: string,
  linkTitle: string,
  titleByPath?: ReadonlyMap<string, string>,
): { label: string; fullTitle?: string } {
  const normalized = normalizeNoteCitationPath(href);
  const canonical = normalized ? titleByPath?.get(normalized) : undefined;
  const fullTitle = (canonical || linkTitle).trim() || undefined;
  const fallback = isPostCitationHref(href) ? "Пост" : "Заметка";
  return {
    label: citationChipLabel(canonical || linkTitle, fallback),
    fullTitle,
  };
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
 * Pull citation links out of paragraph text and append them at the paragraph end.
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

export function prepareNoteCitationsForDisplay(
  text: string,
  validPaths?: ReadonlySet<string>,
  titleByPath?: ReadonlyMap<string, string>,
): string {
  const normalized = normalizeNoteCitationMarkdown(text);
  const validated =
    validPaths !== undefined ? stripInvalidNoteCitations(normalized, validPaths) : normalized;
  const titled = titleByPath ? rewriteNoteCitationLinkTitles(validated, titleByPath) : validated;
  return detachNoteCitations(titled);
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
