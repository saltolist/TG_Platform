import type { NoteFile } from "@/shared/types";
import { ATTACHMENT_PREFIX } from "@/widgets/note-editor/lib/noteMarkdownBridge";

/**
 * The note's BlockNote document is stored as JSON (source of truth). Media
 * sources inside it are kept in the stable `attachment:<id>` form. These
 * helpers convert between that stored form and live, resolvable URLs:
 *
 * - resolve (load): attachment:<id> -> file.url, for display in the editor.
 * - restore (save): file.url -> attachment:<id>, for stable storage.
 *
 * Only known source fields are touched (`props.url` on blocks and `href` on
 * link inline content), so user text is never accidentally rewritten.
 */

type Direction = "resolve" | "restore";

function fileKey(file: NoteFile): string {
  return file.id ?? file.name;
}

function transform(value: string, dir: Direction, files: NoteFile[]): string {
  if (dir === "resolve") {
    if (!value.startsWith(ATTACHMENT_PREFIX)) return value;
    const id = value.slice(ATTACHMENT_PREFIX.length);
    const file = files.find((f) => f.id === id || f.name === id);
    return file?.url ?? value;
  }
  const file = files.find((f) => f.url && f.url === value);
  return file ? `${ATTACHMENT_PREFIX}${fileKey(file)}` : value;
}

function walk(node: unknown, dir: Direction, files: NoteFile[]): unknown {
  if (Array.isArray(node)) return node.map((item) => walk(item, dir, files));
  if (!node || typeof node !== "object") return node;

  const source = node as Record<string, unknown>;
  const out: Record<string, unknown> = { ...source };

  if (source.props && typeof source.props === "object") {
    const props = { ...(source.props as Record<string, unknown>) };
    if (typeof props.url === "string") props.url = transform(props.url, dir, files);
    out.props = props;
  }
  if (typeof source.href === "string") {
    out.href = transform(source.href, dir, files);
  }
  if (source.content !== undefined) out.content = walk(source.content, dir, files);
  if (source.children !== undefined) out.children = walk(source.children, dir, files);

  return out;
}

/** attachment:<id> -> resolvable URLs (before loading into the editor). */
export function resolveDocAttachments(doc: unknown[], files: NoteFile[]): unknown[] {
  return walk(doc, "resolve", files) as unknown[];
}

/** Resolvable URLs -> attachment:<id> (before storing the document). */
export function restoreDocAttachments(doc: unknown[], files: NoteFile[]): unknown[] {
  return walk(doc, "restore", files) as unknown[];
}
