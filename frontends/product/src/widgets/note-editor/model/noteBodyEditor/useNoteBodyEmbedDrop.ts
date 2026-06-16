"use client";

import { useCallback, type RefObject } from "react";
import { TEXT_DROP_BOUNDARY_FRAC } from "@/widgets/note-editor/ui/noteBodyEditor/constants";
import {
  hitTestLine,
  isImageGridLineBeforeDrop,
  normalizeImageGridAdjacentNoop,
  resolveFlexEmbedDrop,
  resolveImageGridSlot,
  stabilizeDropBeforeCommitted,
  textLineCellMetrics,
} from "@/widgets/note-editor/ui/noteBodyEditor/dropUtils";
import type { NoteBodyEmbedDragState } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyEmbedDragState";
import {
  findNoteFile,
  imageGridSlotToDropBefore,
  insertEmbedAt,
  insertEmbedInBody,
  isDropNoop,
  isImageEmbedRow,
  isTextLine,
  moveEmbedAt,
  moveEmbedToImageGridSlot,
  moveEmbedToLineBefore,
  type BodyLine,
  type CellPos,
} from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

type Params = {
  drag: NoteBodyEmbedDragState;
  canvasRef: RefObject<HTMLDivElement | null>;
  bodyRef: RefObject<string>;
  linesRef: RefObject<BodyLine[]>;
  filesRef: RefObject<NoteFile[]>;
  applyLines: (next: BodyLine[]) => void;
  onBodyChange: (body: string) => void;
  isView: boolean;
  onAddFile: (file: File) => NoteFile;
};

export function useNoteBodyEmbedDrop({
  drag,
  canvasRef,
  bodyRef,
  linesRef,
  filesRef,
  applyLines,
  onBodyChange,
  isView,
  onAddFile,
}: Params) {
  const {
    dragFromRef,
    dragSourceRef,
    imageDropSlotRef,
    dropLineBeforeRef,
    currentDropRef,
    committedSlotRef,
    dropCommittedRef,
    dragMovedRef,
    setDropBefore,
    setImageSlot,
    setImageDropSlot,
    setDropLineBefore,
    clearDrag,
  } = drag;

  const resolveDropBefore = useCallback(
    (clientX: number, clientY: number): CellPos => {
      const from = dragSourceRef.current ?? dragFromRef.current;
      const curLines = linesRef.current;
      const curFiles = filesRef.current;

      const hit = hitTestLine(clientX, clientY, curLines, curFiles);
      const slotState = imageDropSlotRef.current;

      if (hit?.lineEl.dataset.dropTail === "1") {
        return { line: curLines.length, cell: 0 };
      }

      if (hit?.isImageGrid && from && isImageGridLineBeforeDrop(clientY, hit.lineEl)) {
        return { line: hit.lineIndex, cell: 0 };
      }

      if (hit && slotState && slotState.line === hit.lineIndex && isImageEmbedRow(hit.line, curFiles)) {
        return imageGridSlotToDropBefore(hit.line, hit.lineIndex, slotState.slot, from);
      }

      if (!hit) return { line: curLines.length, cell: 0 };

      if (isTextLine(hit.line)) {
        const { top, height: h } = textLineCellMetrics(hit.lineEl);
        const boundaryY = top + h * TEXT_DROP_BOUNDARY_FRAC;
        if (clientY < boundaryY) return { line: hit.lineIndex, cell: 0 };
        return { line: hit.lineIndex + 1, cell: 0 };
      }

      if (hit.isImageGrid && from) {
        const slot = resolveImageGridSlot(
          clientX,
          hit.lineEl,
          hit.lineIndex,
          hit.line,
          dragSourceRef.current ?? dragFromRef.current,
          committedSlotRef,
          imageDropSlotRef,
        );
        return imageGridSlotToDropBefore(hit.line, hit.lineIndex, slot, from);
      }

      if (from) return resolveFlexEmbedDrop(clientX, hit.line, hit.lineIndex);
      return { line: hit.lineIndex, cell: 0 };
    },
    [
      committedSlotRef,
      dragFromRef,
      dragSourceRef,
      filesRef,
      imageDropSlotRef,
      linesRef,
    ],
  );

  const commitDropAt = useCallback(
    (before: CellPos, embedName?: string) => {
      const from = dragSourceRef.current ?? dragFromRef.current;

      if (!isView && from == null && embedName && findNoteFile(filesRef.current, embedName)) {
        const body = bodyRef.current;
        const textarea = canvasRef.current?.querySelector<HTMLTextAreaElement>(
          ".note-body-document-edit--mirror",
        );
        const offset = textarea?.selectionStart ?? body.length;
        onBodyChange(insertEmbedInBody(body, offset, embedName));
        clearDrag();
        return;
      }

      const curLines = linesRef.current;
      const curFiles = filesRef.current;
      const currentDrop = currentDropRef.current;
      const lineBefore = currentDrop?.type === "lineBefore" ? currentDrop.line : null;
      const rawCommittedBefore = currentDrop?.type === "before" ? currentDrop.before : before;
      const committedBefore =
        from != null && dragMovedRef.current
          ? normalizeImageGridAdjacentNoop(from, rawCommittedBefore, curLines, curFiles)
          : rawCommittedBefore;

      if (from != null) {
        if (lineBefore != null) {
          applyLines(moveEmbedToLineBefore(curLines, from, lineBefore, curFiles));
        } else if (currentDrop?.type === "imageSlot") {
          applyLines(moveEmbedToImageGridSlot(curLines, from, currentDrop.line, currentDrop.slot, curFiles));
        } else if (!isDropNoop(from, committedBefore)) {
          applyLines(moveEmbedAt(curLines, from, committedBefore, curFiles));
        }
      } else if (embedName && findNoteFile(curFiles, embedName)) {
        applyLines(insertEmbedAt(curLines, committedBefore, embedName, curFiles));
      }
      clearDrag();
    },
    [
      applyLines,
      bodyRef,
      canvasRef,
      clearDrag,
      currentDropRef,
      dragFromRef,
      dragMovedRef,
      dragSourceRef,
      filesRef,
      isView,
      linesRef,
      onBodyChange,
    ],
  );

  const updateDropTarget = useCallback(
    (clientX: number, clientY: number) => {
      const hit = hitTestLine(clientX, clientY, linesRef.current, filesRef.current);
      const lineBefore =
        hit?.isImageGrid && dragSourceRef.current != null && isImageGridLineBeforeDrop(clientY, hit.lineEl)
          ? hit.lineIndex
          : null;

      if (lineBefore != null) {
        if (imageDropSlotRef.current != null) {
          imageDropSlotRef.current = null;
          setImageDropSlot(null);
        }
        currentDropRef.current = { type: "lineBefore", line: lineBefore };
        if (dropLineBeforeRef.current !== lineBefore) {
          dropLineBeforeRef.current = lineBefore;
          setDropLineBefore(lineBefore);
        }
      } else if (dropLineBeforeRef.current != null) {
        dropLineBeforeRef.current = null;
        setDropLineBefore(null);
      }

      if (hit?.isImageGrid && lineBefore == null) {
        const from = dragSourceRef.current ?? dragFromRef.current;
        const slot = resolveImageGridSlot(
          clientX,
          hit.lineEl,
          hit.lineIndex,
          hit.line,
          from,
          committedSlotRef,
          imageDropSlotRef,
        );
        const before = imageGridSlotToDropBefore(hit.line, hit.lineIndex, slot, from);
        currentDropRef.current = { type: "imageSlot", line: hit.lineIndex, slot };
        dropCommittedRef.current = before;
        setDropBefore((prev) =>
          prev && prev.line === before.line && prev.cell === before.cell ? prev : before,
        );
        setImageSlot(hit.lineIndex, slot);
        return;
      } else if (imageDropSlotRef.current != null) {
        imageDropSlotRef.current = null;
        setImageDropSlot(null);
      }

      if (dragSourceRef.current != null) {
        const raw = resolveDropBefore(clientX, clientY);
        const stable = stabilizeDropBeforeCommitted(
          dropCommittedRef.current,
          raw,
          clientX,
          clientY,
          linesRef.current,
          filesRef.current,
        );
        dropCommittedRef.current = stable;
        currentDropRef.current = { type: "before", before: stable };
        setDropBefore((prev) =>
          prev && prev.line === stable.line && prev.cell === stable.cell ? prev : stable,
        );
      }
    },
    [
      committedSlotRef,
      currentDropRef,
      dragFromRef,
      dragSourceRef,
      dropCommittedRef,
      dropLineBeforeRef,
      filesRef,
      imageDropSlotRef,
      linesRef,
      resolveDropBefore,
      setDropBefore,
      setDropLineBefore,
      setImageDropSlot,
      setImageSlot,
    ],
  );

  const resolveDropForCommit = useCallback(
    (clientX: number, clientY: number): CellPos => {
      const from = dragSourceRef.current ?? dragFromRef.current;
      const curLines = linesRef.current;
      const curFiles = filesRef.current;
      const hit = hitTestLine(clientX, clientY, curLines, curFiles);

      if (hit?.isImageGrid && from) {
        if (isImageGridLineBeforeDrop(clientY, hit.lineEl)) {
          imageDropSlotRef.current = null;
          dropLineBeforeRef.current = hit.lineIndex;
          const before = { line: hit.lineIndex, cell: 0 };
          dropCommittedRef.current = before;
          currentDropRef.current = { type: "lineBefore", line: hit.lineIndex };
          return before;
        }

        const slot = resolveImageGridSlot(
          clientX,
          hit.lineEl,
          hit.lineIndex,
          hit.line,
          from,
          committedSlotRef,
          imageDropSlotRef,
        );
        imageDropSlotRef.current = { line: hit.lineIndex, slot };
        dropLineBeforeRef.current = null;
        const before = imageGridSlotToDropBefore(hit.line, hit.lineIndex, slot, from);
        dropCommittedRef.current = before;
        currentDropRef.current = { type: "imageSlot", line: hit.lineIndex, slot };
        return before;
      }

      if (currentDropRef.current?.type === "before") return currentDropRef.current.before;
      if (currentDropRef.current?.type === "imageSlot") {
        const line = curLines[currentDropRef.current.line];
        if (line) {
          return imageGridSlotToDropBefore(line, currentDropRef.current.line, currentDropRef.current.slot, from);
        }
      }
      if (currentDropRef.current?.type === "lineBefore") return { line: currentDropRef.current.line, cell: 0 };
      return dropCommittedRef.current ?? resolveDropBefore(clientX, clientY);
    },
    [
      committedSlotRef,
      currentDropRef,
      dragFromRef,
      dragSourceRef,
      dropCommittedRef,
      dropLineBeforeRef,
      filesRef,
      imageDropSlotRef,
      linesRef,
      resolveDropBefore,
    ],
  );

  const performDrop = useCallback(
    (clientX: number, clientY: number, dataTransfer: DataTransfer | null, embedMime: string) => {
      const before =
        dragSourceRef.current != null
          ? resolveDropForCommit(clientX, clientY)
          : resolveDropBefore(clientX, clientY);

      if (dataTransfer?.files?.length) {
        const file = dataTransfer.files[0];
        if (file) {
          const entry = onAddFile(file);
          commitDropAt(before, entry.name);
        }
        return;
      }

      const embedName = dataTransfer?.getData(embedMime) || undefined;
      commitDropAt(before, embedName || undefined);
    },
    [commitDropAt, dragSourceRef, onAddFile, resolveDropBefore, resolveDropForCommit],
  );

  return {
    commitDropAt,
    updateDropTarget,
    resolveDropForCommit,
    performDrop,
  };
}
