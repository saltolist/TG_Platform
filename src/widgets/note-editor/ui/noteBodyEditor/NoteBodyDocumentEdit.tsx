"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";

import {
  focusNoteBodyAtPoint,
  shouldHandleBodyCanvasPointerDown,
} from "@/widgets/note-editor/lib/noteBodyCanvasFocus";
import { splitLineHighlightParts } from "@/shared/lib/noteEmbeds/lineHighlight";

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

function renderHighlight(body: string): ReactNode {
  const parts = splitLineHighlightParts(body);
  if (parts.length === 0) {
    return "\u00a0";
  }

  const nodes: ReactNode[] = [];
  parts.forEach((part, index) => {
    if (part.type === "embed") {
      nodes.push(
        <span key={`embed-${index}`} className="note-embed-token">
          {part.value}
        </span>,
      );
      return;
    }
    nodes.push(part.value);
  });
  return nodes;
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

  return (
    <div className="note-body-document note-body-document--edit">
      <div
        ref={stackRef}
        className="note-body-document-edit-stack"
        onMouseDown={handleStackMouseDown}
      >
        <div className="note-body-document-edit-highlight" aria-hidden>
          {renderHighlight(body)}
        </div>
        <textarea
          ref={textareaRef}
          className="note-body-document-edit note-body-document-edit--mirror"
          value={body}
          rows={1}
          spellCheck
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}
