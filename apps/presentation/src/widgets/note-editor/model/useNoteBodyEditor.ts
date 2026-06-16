"use client";

import { useNoteBodyEmbedDrag } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyEmbedDrag";
import { useNoteBodyLines } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyLines";
import { useNoteBodyViewMode } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyViewMode";
import type { NoteBodyEditorProps } from "@/widgets/note-editor/ui/noteBodyEditor/types";

export function useNoteBodyEditor({
  body,
  files,
  isView,
  onBodyChange,
  onAddFile,
  onEditRequest,
  focusRequest = 0,
}: NoteBodyEditorProps) {
  const lines = useNoteBodyLines({ body, files, onBodyChange });

  const drag = useNoteBodyEmbedDrag({
    canvasRef: lines.canvasRef,
    bodyRef: lines.bodyRef,
    linesRef: lines.linesRef,
    filesRef: lines.filesRef,
    lines: lines.lines,
    applyLines: lines.applyLines,
    onBodyChange,
    isView,
    onAddFile,
  });

  const viewMode = useNoteBodyViewMode({
    canvasRef: lines.canvasRef,
    isView,
    focusRequest,
    onEditRequest,
  });

  return {
    canvasRef: lines.canvasRef,
    lines: lines.lines,
    files: lines.files,
    isView,
    isDragging: drag.isDragging,
    hasContent: lines.hasContent,
    dragFrom: drag.dragFrom,
    dropBefore: drag.dropBefore,
    imageDropSlot: drag.imageDropSlot,
    dropLineBefore: drag.dropLineBefore,
    dropGapActive: drag.dropGapActive,
    dropLineBeforeActive: drag.dropLineBeforeActive,
    draggedEmbedCell: drag.draggedEmbedCell,
    dragFloatMountRef: drag.dragFloatMountRef,
    applyLines: lines.applyLines,
    beginEmbedPointerDrag: drag.beginEmbedPointerDrag,
    handleCanvasDragOver: drag.handleCanvasDragOver,
    handleViewDoubleClick: viewMode.handleViewDoubleClick,
    handleEditCanvasMouseDown: viewMode.handleEditCanvasMouseDown,
  };
}
