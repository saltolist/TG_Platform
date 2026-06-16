"use client";

import { useEffect, type RefObject } from "react";
import { EMBED_MIME } from "@/widgets/note-editor/ui/noteBodyEditor/constants";
import { useNoteBodyEmbedDragState } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyEmbedDragState";
import { useNoteBodyEmbedDrop } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyEmbedDrop";
import { useNoteBodyEmbedPointer } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyEmbedPointer";
import { isDropNoop, type BodyLine } from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

type Params = {
  canvasRef: RefObject<HTMLDivElement | null>;
  bodyRef: RefObject<string>;
  linesRef: RefObject<BodyLine[]>;
  filesRef: RefObject<NoteFile[]>;
  lines: BodyLine[];
  applyLines: (next: BodyLine[]) => void;
  onBodyChange: (body: string) => void;
  isView: boolean;
  onAddFile: (file: File) => NoteFile;
};

export function useNoteBodyEmbedDrag({
  canvasRef,
  bodyRef,
  linesRef,
  filesRef,
  lines,
  applyLines,
  onBodyChange,
  isView,
  onAddFile,
}: Params) {
  const drag = useNoteBodyEmbedDragState();
  const drop = useNoteBodyEmbedDrop({
    drag,
    canvasRef,
    bodyRef,
    linesRef,
    filesRef,
    applyLines,
    onBodyChange,
    isView,
    onAddFile,
  });
  const pointer = useNoteBodyEmbedPointer({ drag, filesRef, drop });

  useEffect(() => {
    const onDocDragOver = (e: DragEvent) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const r = canvas.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom) return;

      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = drag.dragFromRef.current != null ? "move" : "copy";
      }
      if (drag.dragSourceRef.current != null) {
        drag.syncDragFloatPosition(e.clientX, e.clientY);
      }
      drop.updateDropTarget(e.clientX, e.clientY);
    };

    const onDocDrop = (e: DragEvent) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const r = canvas.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom) return;
      e.preventDefault();
      drop.performDrop(e.clientX, e.clientY, e.dataTransfer, EMBED_MIME);
    };

    document.addEventListener("dragover", onDocDragOver);
    document.addEventListener("drop", onDocDrop);
    return () => {
      document.removeEventListener("dragover", onDocDragOver);
      document.removeEventListener("drop", onDocDrop);
    };
  }, [canvasRef, drag, drop]);

  const handleCanvasDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = drag.dragFromRef.current != null ? "move" : "copy";
    if (drag.dragSourceRef.current != null) {
      drag.syncDragFloatPosition(e.clientX, e.clientY);
    }
    drop.updateDropTarget(e.clientX, e.clientY);
  };

  const isDragging = drag.dragFrom != null;
  const draggedEmbedCell =
    drag.dragFrom != null && lines[drag.dragFrom.line]?.cells[drag.dragFrom.cell]?.type === "embed"
      ? lines[drag.dragFrom.line]!.cells[drag.dragFrom.cell]!
      : null;
  const dropGapActive =
    drag.dragFrom != null && drag.dropBefore != null && !isDropNoop(drag.dragFrom, drag.dropBefore);
  const dropLineBeforeActive = drag.dragFrom != null && drag.dropLineBefore != null;

  return {
    dragFrom: drag.dragFrom,
    dropBefore: drag.dropBefore,
    imageDropSlot: drag.imageDropSlot,
    dropLineBefore: drag.dropLineBefore,
    isDragging,
    draggedEmbedCell,
    dropGapActive,
    dropLineBeforeActive,
    dragFloatMountRef: drag.dragFloatMountRef,
    beginEmbedPointerDrag: pointer.beginEmbedPointerDrag,
    handleCanvasDragOver,
  };
}
