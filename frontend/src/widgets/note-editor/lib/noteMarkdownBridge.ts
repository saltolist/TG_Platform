import { isNoteImageFile } from "@/shared/lib/noteDraft";
import type { NoteFile } from "@/shared/types";

export const ATTACHMENT_PREFIX = "attachment:";

const ATTACHMENT_URL_RE = /(\]\()attachment:([^)]+)(\))/g;
/** Markdown image line: ![alt](url) — not file chips [name](url). */
const MARKDOWN_IMAGE_LINE_RE = /^\!\[[^\]]*\]\([^)]+\)\s*$/;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function findFileById(files: NoteFile[], id: string): NoteFile | undefined {
  return files.find((file) => file.id === id || file.name === id);
}

/** Markdown snippet for a note attachment (canonical storage format). */
export function attachmentMarkdown(file: NoteFile): string {
  const id = file.id ?? file.name;
  if (isNoteImageFile(file)) {
    return `![${file.name}](${ATTACHMENT_PREFIX}${id})`;
  }
  return `[${file.name}](${ATTACHMENT_PREFIX}${id})`;
}

/** Replace attachment:<id> links with resolvable URLs before BlockNote import. */
export function resolveAttachmentsToUrls(markdown: string, files: NoteFile[]): string {
  return (markdown ?? "").replace(ATTACHMENT_URL_RE, (_match, prefix: string, id: string, suffix: string) => {
    const file = findFileById(files, id);
    if (file?.url) {
      return `${prefix}${file.url}${suffix}`;
    }
    return `${prefix}${ATTACHMENT_PREFIX}${id}${suffix}`;
  });
}

/** Replace known file URLs back to attachment:<id> after BlockNote export. */
export function resolveUrlsToAttachments(markdown: string, files: NoteFile[]): string {
  let result = markdown ?? "";
  for (const file of files) {
    if (!file.id || !file.url) continue;
    result = result.replace(new RegExp(`\\(${escapeRegExp(file.url)}\\)`, "g"), `(${ATTACHMENT_PREFIX}${file.id})`);
  }
  return result;
}

/**
 * Remove blank lines between consecutive markdown image lines so view-mode
 * image grid grouping works (see docs/dev/note-format.md).
 */
export function compactAttachmentImageRows(markdown: string): string {
  const lines = (markdown ?? "").split("\n");
  const result: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (line.trim() !== "") {
      result.push(line);
      continue;
    }

    const prevIsImage =
      result.length > 0 && MARKDOWN_IMAGE_LINE_RE.test(result[result.length - 1]!);
    let nextIdx = i;
    while (nextIdx < lines.length && lines[nextIdx]!.trim() === "") nextIdx++;
    const nextIsImage =
      nextIdx < lines.length && MARKDOWN_IMAGE_LINE_RE.test(lines[nextIdx]!);

    if (prevIsImage && nextIsImage) {
      i = nextIdx - 1;
      continue;
    }

    result.push(line);
  }

  return result.join("\n");
}
