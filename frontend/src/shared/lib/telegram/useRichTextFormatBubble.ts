import { useCallback, useEffect, useState, type RefObject } from "react";

export type RichTextFormatBubbleState = {
  open: boolean;
  top: number;
  left: number;
};

export function useRichTextFormatBubble(
  editorRef: RefObject<HTMLElement | null>,
  disabled: boolean,
) {
  const [bubble, setBubble] = useState<RichTextFormatBubbleState>({
    open: false,
    top: 0,
    left: 0,
  });

  const refreshBubble = useCallback(() => {
    const root = editorRef.current;
    if (!root || disabled) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    const rect = range.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      setBubble((current) => (current.open ? { ...current, open: false } : current));
      return;
    }

    setBubble({
      open: true,
      top: rect.top - 8,
      left: rect.left + rect.width / 2,
    });
  }, [disabled, editorRef]);

  const closeBubble = useCallback(() => {
    setBubble((current) => (current.open ? { ...current, open: false } : current));
  }, []);

  useEffect(() => {
    document.addEventListener("selectionchange", refreshBubble);
    window.addEventListener("resize", refreshBubble);
    window.addEventListener("scroll", refreshBubble, true);
    return () => {
      document.removeEventListener("selectionchange", refreshBubble);
      window.removeEventListener("resize", refreshBubble);
      window.removeEventListener("scroll", refreshBubble, true);
    };
  }, [refreshBubble]);

  return { bubble, refreshBubble, closeBubble };
}
