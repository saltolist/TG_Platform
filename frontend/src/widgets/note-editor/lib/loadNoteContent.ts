import { BlockNoteEditor, type PartialBlock } from "@blocknote/core";

import type { NoteFile } from "@/shared/types";
import { resolveAttachmentsToUrls } from "@/widgets/note-editor/lib/noteMarkdownBridge";
import { resolveDocAttachments } from "@/widgets/note-editor/lib/noteDocAttachments";
import { sanitizeNoteDoc } from "@/widgets/note-editor/lib/sanitizeNoteDoc";

export function buildNoteDocBlocks(doc: unknown[], files: NoteFile[]): PartialBlock[] {
  const resolved = resolveDocAttachments(doc, files);
  return sanitizeNoteDoc(resolved);
}

function canLoadBlocks(blocks: PartialBlock[]): boolean {
  try {
    BlockNoteEditor.create({ initialContent: blocks, trailingBlock: false });
    return true;
  } catch {
    return false;
  }
}

function stripAllChildren(blocks: PartialBlock[]): PartialBlock[] {
  return blocks.map((block) => {
    const next = { ...block } as PartialBlock & { children?: PartialBlock[] };
    delete next.children;
    return next;
  });
}

function tryReplaceBlocks(editor: BlockNoteEditor, blocks: PartialBlock[]): boolean {
  if (blocks.length === 0) return false;
  if (!canLoadBlocks(blocks)) return false;
  try {
    editor.replaceBlocks(editor.document, blocks);
    return true;
  } catch {
    return false;
  }
}

export function loadNoteContentIntoEditor(
  editor: BlockNoteEditor,
  options: { doc?: unknown[]; body: string; files: NoteFile[] },
): boolean {
  if (options.doc && options.doc.length > 0) {
    const blocks = buildNoteDocBlocks(options.doc, options.files);
    if (tryReplaceBlocks(editor, blocks)) return true;

    const flattened = stripAllChildren(blocks);
    if (flattened.length > 0 && tryReplaceBlocks(editor, flattened)) return true;
  }

  if (!options.body.trim()) return false;

  try {
    const markdown = resolveAttachmentsToUrls(options.body, options.files);
    const blocks = editor.tryParseMarkdownToBlocks(markdown);
    if (blocks.length > 0) {
      editor.replaceBlocks(editor.document, blocks);
      return true;
    }
  } catch {
    // keep empty document
  }

  return false;
}
