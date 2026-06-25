import { isNoteImageFile } from "@/shared/lib/noteDraft";
import type { NoteFile } from "@/shared/types";

export const ATTACHMENT_PREFIX = "attachment:";

/** Matches the URL part of a markdown link/image that points to an attachment: `](attachment:<id>)`. */
const ATTACHMENT_LINK_RE = /(\]\()attachment:([^)]+)(\))/g;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function fileKey(file: NoteFile): string {
  return file.id ?? file.name;
}

function findFile(files: NoteFile[], id: string): NoteFile | undefined {
  return files.find((file) => file.id === id || file.name === id);
}

/**
 * Replace `attachment:<id>` links with resolvable file URLs before importing
 * markdown into BlockNote (so images/links render with real sources).
 * Unknown ids are left untouched.
 */
export function resolveAttachmentsToUrls(markdown: string, files: NoteFile[]): string {
  return (markdown ?? "").replace(
    ATTACHMENT_LINK_RE,
    (whole, open: string, id: string, close: string) => {
      const file = findFile(files, id);
      return file?.url ? `${open}${file.url}${close}` : whole;
    },
  );
}

/**
 * Replace known file URLs back to `attachment:<id>` after exporting markdown
 * from BlockNote, so the canonical storage format is preserved.
 */
export function restoreUrlsToAttachments(markdown: string, files: NoteFile[]): string {
  let result = markdown ?? "";
  for (const file of files) {
    if (!file.url) continue;
    const id = fileKey(file);
    result = result.replace(
      new RegExp(`\\(${escapeRegExp(file.url)}\\)`, "g"),
      `(${ATTACHMENT_PREFIX}${id})`,
    );
  }
  return result;
}

/** Canonical markdown snippet for an attachment (image vs file chip). */
export function attachmentMarkdown(file: NoteFile): string {
  const id = fileKey(file);
  return isNoteImageFile(file)
    ? `![${file.name}](${ATTACHMENT_PREFIX}${id})`
    : `[${file.name}](${ATTACHMENT_PREFIX}${id})`;
}
