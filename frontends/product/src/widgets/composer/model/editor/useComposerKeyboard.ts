"use client";

import { useCallback } from "react";
import type { Post } from "@/shared/types";

type Params = {
  narrowComposer: boolean;
  mentionOpen: boolean;
  mentionMatches: Post[];
  mentionIndex: number;
  setMentionIndex: (index: number | ((i: number) => number)) => void;
  pickMention: (post: Post) => void;
  clearMention: () => void;
  submit: () => void;
  refreshIsEmpty: () => void;
  refreshMention: () => void;
  syncAttachmentsFromDom: () => void;
};

export function useComposerKeyboard({
  narrowComposer,
  mentionOpen,
  mentionMatches,
  mentionIndex,
  setMentionIndex,
  pickMention,
  clearMention,
  submit,
  refreshIsEmpty,
  refreshMention,
  syncAttachmentsFromDom,
}: Params) {
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (mentionOpen) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setMentionIndex((i) => (i + 1) % mentionMatches.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length);
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          pickMention(mentionMatches[mentionIndex]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          clearMention();
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        if (narrowComposer) return;
        e.preventDefault();
        submit();
      }
    },
    [
      clearMention,
      mentionOpen,
      mentionIndex,
      mentionMatches,
      narrowComposer,
      pickMention,
      setMentionIndex,
      submit,
    ],
  );

  const onEditorInput = useCallback(() => {
    syncAttachmentsFromDom();
    refreshIsEmpty();
    refreshMention();
  }, [refreshIsEmpty, refreshMention, syncAttachmentsFromDom]);

  const onPaste = useCallback(
    (e: React.ClipboardEvent<HTMLDivElement>) => {
      e.preventDefault();
      const text = e.clipboardData.getData("text/plain");
      if (!text) return;
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      range.deleteContents();
      const parts = text.split("\n");
      parts.forEach((part, i) => {
        if (i > 0) range.insertNode(document.createElement("br"));
        if (part) range.insertNode(document.createTextNode(part));
        range.collapse(false);
      });
      refreshIsEmpty();
      refreshMention();
    },
    [refreshIsEmpty, refreshMention],
  );

  return { onEditorInput, onKeyDown, onPaste };
}
