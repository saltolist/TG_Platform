"use client";

import { useCallback, useEffect, useRef } from "react";

import {
  focusNoteBodyAtPoint,
  shouldHandleBodyCanvasPointerDown,
} from "@/widgets/note-editor/lib/noteBodyCanvasFocus";

const EMBED_MIME = "application/x-note-embed";

type Props = {
  body: string;
  onChange: (body: string) => void;
};

function autoGrow(el: HTMLTextAreaElement) {
  const canvas = el.closest(".note-body-canvas");
  const minHeight = canvas instanceof HTMLElement ? canvas.clientHeight : 0;
  el.style.height = "auto";
  const contentHeight = el.scrollHeight;
  el.style.height = `${Math.max(contentHeight, minHeight)}px`;
}

/** Insert text at the textarea caret position. */
function insertAtCaret(el: HTMLTextAreaElement, text: string): string {
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  return el.value.slice(0, start) + text + el.value.slice(end);
}

export default function NoteBodyDocumentEdit({ body, onChange }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (textareaRef.current) autoGrow(textareaRef.current);
  }, [body]);

  const handleStackMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const canvas = stackRef.current?.closest(".note-body-canvas");
    if (!(canvas instanceof HTMLElement)) return;
    if (!shouldHandleBodyCanvasPointerDown(e.target, canvas)) return;
    e.preventDefault();
    focusNoteBodyAtPoint(canvas, e.clientX, e.clientY);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes(EMBED_MIME) || e.dataTransfer.types.includes("text/plain")) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLTextAreaElement>) => {
      const mdText = e.dataTransfer.getData("text/plain");
      if (!mdText) return;
      e.preventDefault();
      const el = e.currentTarget;
      el.focus();
      const newBody = insertAtCaret(el, mdText);
      onChange(newBody);
    },
    [onChange],
  );

  return (
    <div className="note-body-document note-body-document--edit">
      <div
        ref={stackRef}
        className="note-body-document-edit-stack"
        onMouseDown={handleStackMouseDown}
      >
        <textarea
          ref={textareaRef}
          className="note-body-document-edit note-body-document-edit--markdown"
          value={body}
          rows={1}
          spellCheck
          placeholder="Заметка в формате Markdown…"
          onChange={(e) => onChange(e.target.value)}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        />
      </div>
    </div>
  );
}
