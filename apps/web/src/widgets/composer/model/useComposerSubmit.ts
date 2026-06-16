"use client";

import { useCallback } from "react";

export function useComposerSubmit(
  serializeEditor: () => string,
  clearEditor: () => void,
  onSubmit: (text: string) => boolean,
) {
  return useCallback(() => {
    const trimmed = serializeEditor().trim();
    if (!trimmed) return;
    const ok = onSubmit(trimmed);
    if (ok) clearEditor();
  }, [clearEditor, onSubmit, serializeEditor]);
}
