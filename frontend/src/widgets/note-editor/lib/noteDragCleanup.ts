import type { BlockNoteEditor } from "@blocknote/core";
import { useEffect, useRef } from "react";

const NOTE_ROOT = "#screen-note";

type BlockWithContent = {
  id: string;
  type: string;
  content?: Array<{ type: string; text?: string }>;
};

type BlockSnapshot = {
  id: string;
  empty: boolean;
};

function isNoteDragHandle(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (!target.closest(NOTE_ROOT)) return false;
  return (
    !!target.closest('[data-test="dragHandle"]') ||
    !!target.closest(".bn-side-menu .bn-button[draggable]")
  );
}

export function isEmptyParagraphBlock(block: BlockWithContent): boolean {
  if (block.type !== "paragraph") return false;
  const content = block.content;
  if (!content || content.length === 0) return true;
  const text = content
    .filter((item) => item.type === "text")
    .map((item) => item.text ?? "")
    .join("");
  return !text.trim();
}

function snapshotTopLevel(editor: BlockNoteEditor): BlockSnapshot[] {
  return (editor.document as BlockWithContent[]).map((block) => ({
    id: block.id,
    empty: isEmptyParagraphBlock(block),
  }));
}

/** Remove empty paragraph blocks created during a side-menu drag. */
export function pruneExcessEmptyParagraphs(
  editor: BlockNoteEditor,
  before: BlockSnapshot[],
): void {
  const after = editor.document as BlockWithContent[];
  if (after.length <= 1) return;

  const beforeById = new Map(before.map((block) => [block.id, block]));
  const beforeEmptyCount = before.filter((block) => block.empty).length;
  const afterEmpties = after.filter(isEmptyParagraphBlock);
  const excess = afterEmpties.length - beforeEmptyCount;
  if (excess <= 0) return;

  const toRemove: string[] = [];

  for (const block of afterEmpties) {
    if (toRemove.length >= excess) break;
    const prev = beforeById.get(block.id);
    if (!prev) {
      toRemove.push(block.id);
      continue;
    }
    if (!prev.empty) {
      toRemove.push(block.id);
    }
  }

  if (toRemove.length === 0 || after.length <= toRemove.length) return;

  try {
    editor.removeBlocks(toRemove);
  } catch {
    // BlockNote may have already reconciled the document.
  }
}

/** Drop orphan empty lines left after BlockNote block drag. */
export function useNoteBlockDragCleanup(editor: BlockNoteEditor): void {
  const snapshotRef = useRef<BlockSnapshot[] | null>(null);
  const dragActiveRef = useRef(false);

  useEffect(() => {
    const onDragStart = (event: DragEvent) => {
      if (!isNoteDragHandle(event.target)) return;
      dragActiveRef.current = true;
      snapshotRef.current = snapshotTopLevel(editor);
    };

    const onDragEnd = () => {
      if (!dragActiveRef.current) return;
      dragActiveRef.current = false;
      const before = snapshotRef.current;
      snapshotRef.current = null;
      if (!before) return;

      const run = () => pruneExcessEmptyParagraphs(editor, before);
      run();
      window.setTimeout(() => {
        run();
        window.setTimeout(run, 50);
      }, 0);
    };

    document.addEventListener("dragstart", onDragStart, true);
    document.addEventListener("dragend", onDragEnd, true);

    return () => {
      document.removeEventListener("dragstart", onDragStart, true);
      document.removeEventListener("dragend", onDragEnd, true);
    };
  }, [editor]);
}
