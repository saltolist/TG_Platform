"use client";

import { useCallback, useRef, useState } from "react";
import { createChipElement } from "@/widgets/composer/lib/composerChipUtils";
import {
  collectAttachmentsFromDom,
  isEditorEmpty,
  placeCaretAfter,
  placeCaretAtStart,
  pruneOrphanComposerSpaces,
  serializeEditorContent,
} from "@/widgets/composer/lib/composerEditorDom";
import type { ComposerEditorRefs } from "@/widgets/composer/model/editor/types";
import type { ComposerAttachment } from "@/shared/types";

type Params = Pick<ComposerEditorRefs, "editorRef">;

export function useComposerChips({ editorRef }: Params) {
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [isEmpty, setIsEmpty] = useState(true);
  const attachmentsRef = useRef<ComposerAttachment[]>([]);
  attachmentsRef.current = attachments;

  const refreshIsEmpty = useCallback(() => {
    const editor = editorRef.current;
    setIsEmpty(editor ? isEditorEmpty(editor) : true);
  }, [editorRef]);

  const syncEmptyEditorDom = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    pruneOrphanComposerSpaces(editor);
    if (!isEditorEmpty(editor)) return;
    editor.innerHTML = "";
    editor.focus();
    placeCaretAtStart(editor);
  }, [editorRef]);

  const normalizeEmptyEditorFocus = useCallback(() => {
    const editor = editorRef.current;
    if (!editor || !isEditorEmpty(editor)) return;
    pruneOrphanComposerSpaces(editor);
    if (editor.innerHTML) editor.innerHTML = "";
    requestAnimationFrame(() => {
      if (editorRef.current) placeCaretAtStart(editorRef.current);
    });
  }, [editorRef]);

  const removeChipById = useCallback(
    (id: string) => {
      const editor = editorRef.current;
      if (!editor) return;
      const chip = editor.querySelector(`[data-attach-id="${CSS.escape(id)}"]`);
      if (chip) {
        const next = chip.nextSibling;
        const prev = chip.previousSibling;
        chip.remove();
        if (next?.nodeType === Node.TEXT_NODE) {
          const t = next.textContent || "";
          if (t.replace(/[\u200b\u00a0\s]/g, "").length === 0) next.remove();
        }
        if (prev?.nodeType === Node.TEXT_NODE) {
          const t = prev.textContent || "";
          if (t.replace(/[\u200b\u00a0\s]/g, "").length === 0) prev.remove();
        }
      }
      setAttachments((prev) => prev.filter((a) => a.id !== id));
      pruneOrphanComposerSpaces(editor);
      refreshIsEmpty();
      requestAnimationFrame(() => {
        syncEmptyEditorDom();
        refreshIsEmpty();
      });
    },
    [editorRef, refreshIsEmpty, syncEmptyEditorDom],
  );

  const addAttachmentInline = useCallback(
    (att: ComposerAttachment) => {
      const editor = editorRef.current;
      if (!editor) return;
      if (
        att.kind === "post" &&
        attachmentsRef.current.some((a) => a.kind === "post" && a.postId === att.postId)
      ) {
        return;
      }
      if (
        att.kind === "media" &&
        attachmentsRef.current.some(
          (a) => a.kind === "media" && a.postId === att.postId && a.media === att.media,
        )
      ) {
        return;
      }
      const chip = createChipElement(att, removeChipById);
      const sel = window.getSelection();
      let inserted = false;
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        if (editor.contains(range.startContainer)) {
          range.deleteContents();
          range.insertNode(chip);
          const space = document.createTextNode("\u00A0");
          chip.parentNode?.insertBefore(space, chip.nextSibling);
          placeCaretAfter(space);
          inserted = true;
        }
      }
      if (!inserted) {
        editor.appendChild(chip);
        const space = document.createTextNode("\u00A0");
        editor.appendChild(space);
        placeCaretAfter(space);
        editor.focus();
      }
      setAttachments((prev) => [...prev, att]);
      refreshIsEmpty();
    },
    [editorRef, refreshIsEmpty, removeChipById],
  );

  const collectLiveAttachments = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return [];
    return collectAttachmentsFromDom(editor, attachmentsRef.current);
  }, [editorRef]);

  const serializeEditor = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return "";
    return serializeEditorContent(editor, attachmentsRef.current);
  }, [editorRef]);

  const clearEditorContent = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.innerHTML = "";
    setAttachments([]);
    refreshIsEmpty();
  }, [editorRef, refreshIsEmpty]);

  const syncAttachmentsFromDom = useCallback(() => {
    const live = collectLiveAttachments();
    if (live.length !== attachmentsRef.current.length) {
      setAttachments(live);
    }
  }, [collectLiveAttachments]);

  const appendAttachment = useCallback((att: ComposerAttachment) => {
    setAttachments((prev) => [...prev, att]);
  }, []);

  return {
    attachments,
    isEmpty,
    refreshIsEmpty,
    normalizeEmptyEditorFocus,
    removeChipById,
    addAttachmentInline,
    appendAttachment,
    serializeEditor,
    clearEditorContent,
    syncAttachmentsFromDom,
  };
}
