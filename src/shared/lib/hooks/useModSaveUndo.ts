"use client";

import type { RefObject } from "react";
import { useLayoutEffect } from "react";

function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const el = target as HTMLElement;
  if (typeof el.tagName !== "string") return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return true;
  if (el.isContentEditable) return true;
  return false;
}

function isModKey(event: KeyboardEvent): boolean {
  return event.metaKey || event.ctrlKey;
}

/** Block browser-level undo (e.g. reopen tab) when the focused field has nothing to undo. */
export function blockBrowserUndoWhenFieldStackEmpty(event: KeyboardEvent): void {
  if (event.defaultPrevented) return;
  if (!isEditableTarget(event.target)) return;

  try {
    if (!document.queryCommandEnabled("undo")) {
      event.preventDefault();
    }
  } catch {
    event.preventDefault();
  }
}

export type ModSaveUndoOptions = {
  active?: boolean;
  dirty: boolean;
  onSave: () => void;
  scopeRef?: RefObject<HTMLElement | null>;
};

/**
 * Cmd/Ctrl+S: save the scoped section when dirty.
 * Cmd/Ctrl+Z in a field: native per-field undo; block browser default when stack is empty.
 */
export function useModSaveUndo({
  active = true,
  dirty,
  onSave,
  scopeRef,
}: ModSaveUndoOptions): void {
  useLayoutEffect(() => {
    if (!active) return;

    const scope = scopeRef?.current ?? null;
    if (!scope) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (e.isComposing) return;
      if (e.repeat) return;
      if (!isModKey(e)) return;

      const target = e.target;
      if (!(target instanceof Node) || !scope.contains(target)) return;

      const key = e.key.toLowerCase();

      if (key === "s") {
        if (!dirty) return;
        e.preventDefault();
        onSave();
        return;
      }

      if (key === "z" && !e.shiftKey) {
        blockBrowserUndoWhenFieldStackEmpty(e);
      }
    };

    scope.addEventListener("keydown", onKeyDown);
    return () => scope.removeEventListener("keydown", onKeyDown);
  }, [active, dirty, onSave, scopeRef]);
}
