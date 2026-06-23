"use client";

import { useCallback, useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";

import { shouldHandleBodyCanvasPointerDown } from "@/widgets/note-editor/lib/noteBodyCanvasFocus";

type Params = {
  canvasRef?: RefObject<HTMLDivElement | null>;
  isView: boolean;
  onEditRequest?: () => void;
};

export function useNoteBodyViewMode({ canvasRef, isView, onEditRequest }: Params) {
  const pendingFocusRef = useRef(false);

  const handleViewDoubleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const canvas = canvasRef?.current;
      if (!isView || !canvas || !shouldHandleBodyCanvasPointerDown(event.target, canvas)) return;
      event.preventDefault();
      window.getSelection()?.removeAllRanges();
      pendingFocusRef.current = true;
      onEditRequest?.();
    },
    [canvasRef, isView, onEditRequest],
  );

  useLayoutEffect(() => {
    if (isView || !pendingFocusRef.current) return;
    pendingFocusRef.current = false;
    const canvas = canvasRef?.current;
    const editor = canvas?.querySelector<HTMLElement>(".ProseMirror");
    editor?.focus();
  }, [canvasRef, isView]);

  return { handleViewDoubleClick };
}
