import { useCallback, useEffect, useRef, useState } from "react";
import type { Editor } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";

import { isFormatBubbleSelection } from "@/shared/lib/telegram/tiptap/selectionHasFormatableText";

export type RichTextFormatBubbleState = {
  open: boolean;
  top: number;
  left: number;
};

function bubbleCoords(editor: Editor): Pick<RichTextFormatBubbleState, "top" | "left"> | null {
  if (!isFormatBubbleSelection(editor)) return null;

  const { from, to } = editor.state.selection;
  const start = editor.view.coordsAtPos(from);
  const end = editor.view.coordsAtPos(to);

  return {
    left: (start.left + end.right) / 2,
    top: Math.min(start.top, end.top) - 8,
  };
}

function isNavigationKey(key: string): boolean {
  return (
    key === "ArrowLeft" ||
    key === "ArrowRight" ||
    key === "ArrowUp" ||
    key === "ArrowDown" ||
    key === "Home" ||
    key === "End"
  );
}

export function useRichTextFormatBubble(editor: Editor | null, disabled: boolean) {
  const [bubble, setBubble] = useState<RichTextFormatBubbleState>({
    open: false,
    top: 0,
    left: 0,
  });
  const pointerRef = useRef({ dragged: false, x: 0, y: 0 });
  const shiftHeldRef = useRef(false);

  const tryOpen = useCallback(() => {
    if (!editor || disabled) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    const coords = bubbleCoords(editor);
    if (!coords) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    setBubble({ open: true, ...coords });
  }, [disabled, editor]);

  const syncIfOpen = useCallback(() => {
    if (!editor || disabled) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    setBubble((current) => {
      if (!current.open) return current;
      const coords = bubbleCoords(editor);
      if (!coords) return { ...current, open: false };
      return { ...current, ...coords };
    });
  }, [disabled, editor]);

  const closeBubble = useCallback(() => {
    setBubble((current) => (current.open ? { ...current, open: false } : current));
  }, []);

  useEffect(() => {
    if (!editor) return undefined;

    const dom = editor.view.dom;

    const onSelectionUpdate = () => {
      const { selection } = editor.state;

      if (selection instanceof NodeSelection || !isFormatBubbleSelection(editor)) {
        closeBubble();
        return;
      }

      if (shiftHeldRef.current) {
        tryOpen();
        return;
      }

      syncIfOpen();
    };

    const onMouseDown = (event: MouseEvent) => {
      pointerRef.current = { dragged: false, x: event.clientX, y: event.clientY };
    };

    const onMouseMove = (event: MouseEvent) => {
      const pointer = pointerRef.current;
      if (pointer.dragged) return;
      const distance = Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y);
      if (distance > 4) {
        pointerRef.current.dragged = true;
      }
    };

    const onMouseUp = (event: MouseEvent) => {
      const { dragged } = pointerRef.current;
      pointerRef.current = { dragged: false, x: 0, y: 0 };

      requestAnimationFrame(() => {
        if (!editor || editor.state.selection instanceof NodeSelection) return;
        if (editor.state.selection.empty) return;
        if (!dragged && event.detail < 2) return;
        tryOpen();
      });
    };

    const onKeyDown = (event: KeyboardEvent) => {
      shiftHeldRef.current = event.shiftKey;

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
        requestAnimationFrame(() => tryOpen());
        return;
      }

      if (!event.shiftKey && isNavigationKey(event.key)) {
        closeBubble();
      }
    };

    const onKeyUp = (event: KeyboardEvent) => {
      shiftHeldRef.current = event.shiftKey;
    };

    editor.on("selectionUpdate", onSelectionUpdate);
    dom.addEventListener("mousedown", onMouseDown);
    dom.addEventListener("mousemove", onMouseMove);
    dom.addEventListener("mouseup", onMouseUp);
    dom.addEventListener("keydown", onKeyDown, true);
    dom.addEventListener("keyup", onKeyUp, true);

    return () => {
      editor.off("selectionUpdate", onSelectionUpdate);
      dom.removeEventListener("mousedown", onMouseDown);
      dom.removeEventListener("mousemove", onMouseMove);
      dom.removeEventListener("mouseup", onMouseUp);
      dom.removeEventListener("keydown", onKeyDown, true);
      dom.removeEventListener("keyup", onKeyUp, true);
    };
  }, [closeBubble, editor, syncIfOpen, tryOpen]);

  useEffect(() => {
    const onLayoutChange = () => syncIfOpen();
    window.addEventListener("resize", onLayoutChange);
    window.addEventListener("scroll", onLayoutChange, true);
    return () => {
      window.removeEventListener("resize", onLayoutChange);
      window.removeEventListener("scroll", onLayoutChange, true);
    };
  }, [syncIfOpen]);

  return { bubble, openBubble: tryOpen, closeBubble };
}
