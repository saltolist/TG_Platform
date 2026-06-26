import type { NoteFile } from "@/shared/types";
import { ATTACHMENT_PREFIX } from "@/widgets/note-editor/lib/noteMarkdownBridge";

const objectUrlBySource = new Map<string, string>();

function findFile(files: NoteFile[], id: string): NoteFile | undefined {
  return files.find((file) => file.id === id || file.name === id);
}

/** Desktop Safari + any iOS browser (all use WebKit). */
function prefersObjectUrlForData(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  if (/iPad|iPhone|iPod/i.test(ua)) return true;
  return /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|Edg|OPR|OPiOS|FxiOS/i.test(ua);
}

async function dataUrlToObjectUrl(dataUrl: string): Promise<string> {
  const cached = objectUrlBySource.get(dataUrl);
  if (cached) return cached;
  try {
    const response = await fetch(dataUrl);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    objectUrlBySource.set(dataUrl, objectUrl);
    return objectUrl;
  } catch {
    return dataUrl;
  }
}

/**
 * Resolve a media URL for display in BlockNote (`resolveFileUrl`).
 * Maps `attachment:<id>` to the file registry and, on WebKit, converts `data:`
 * URLs to `blob:` object URLs so Safari can render large inline images.
 */
export async function resolveNoteFileDisplayUrl(
  url: string,
  files: NoteFile[],
): Promise<string> {
  if (!url) return url;

  let resolved = url;
  if (url.startsWith(ATTACHMENT_PREFIX)) {
    const id = url.slice(ATTACHMENT_PREFIX.length);
    resolved = findFile(files, id)?.url ?? url;
  }

  if (resolved.startsWith("data:") && prefersObjectUrlForData()) {
    return dataUrlToObjectUrl(resolved);
  }

  return resolved;
}
