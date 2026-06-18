"use client";

import { useCallback } from "react";

export function useComposerSubmit(
  serializeEditor: () => string,
  clearEditor: () => void,
  onSubmit: (text: string) => boolean,
  isGenerating = false,
) {
  return useCallback(() => {
    if (isGenerating) return;
    const trimmed = serializeEditor().trim();
    if (!trimmed) return;
    const ok = onSubmit(trimmed);
    if (ok) clearEditor();
  }, [clearEditor, isGenerating, onSubmit, serializeEditor]);
}
