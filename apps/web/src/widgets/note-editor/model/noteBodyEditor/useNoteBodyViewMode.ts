"use client";

import { useCallback, useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";

import {
  focusNoteBodyAtPoint,
  refreshBodyCanvasCursor,
  shouldHandleBodyCanvasPointerDown,
} from "@/widgets/note-editor/lib/noteBodyCanvasFocus";

type Params = {
  canvasRef: RefObject<HTMLDivElement | null>;
  isView: boolean;
  focusRequest: number;
  onEditRequest?: () => void;
};

export function useNoteBodyViewMode({ canvasRef, isView, focusRequest, onEditRequest }: Params) {
  const handledFocusRequestRef = useRef(0);
  const pendingFocusPointRef = useRef<{ x: number; y: number } | null>(null);

  const handleViewDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const canvas = canvasRef.current;
      if (!isView || !canvas || !shouldHandleBodyCanvasPointerDown(e.target, canvas)) return;
      e.preventDefault();
      window.getSelection()?.removeAllRanges();
      pendingFocusPointRef.current = { x: e.clientX, y: e.clientY };
      onEditRequest?.();
    },
    [canvasRef, isView, onEditRequest],
  );

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    refreshBodyCanvasCursor(canvas, isView);
    return () => {
      canvas.style.cursor = "";
    };
  }, [canvasRef, isView]);

  useLayoutEffect(() => {
    if (isView) return;
    const point = pendingFocusPointRef.current;
    if (!point) return;
    pendingFocusPointRef.current = null;
    const canvas = canvasRef.current;
    if (!canvas) return;
    focusNoteBodyAtPoint(canvas, point.x, point.y);
  }, [canvasRef, isView]);

  const handleEditCanvasMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const canvas = canvasRef.current;
      if (isView || !canvas || !shouldHandleBodyCanvasPointerDown(e.target, canvas)) return;
      e.preventDefault();
      focusNoteBodyAtPoint(canvas, e.clientX, e.clientY);
    },
    [canvasRef, isView],
  );

  useLayoutEffect(() => {
    if (isView || focusRequest <= handledFocusRequestRef.current) return;
    handledFocusRequestRef.current = focusRequest;
    const editor = canvasRef.current?.querySelector<HTMLTextAreaElement>(
      ".note-body-document-edit--mirror",
    );
    if (!editor) return;
    editor.focus();
    const end = editor.value.length;
    editor.setSelectionRange(end, end);
  }, [canvasRef, focusRequest, isView]);

  return { handleViewDoubleClick, handleEditCanvasMouseDown };
}
