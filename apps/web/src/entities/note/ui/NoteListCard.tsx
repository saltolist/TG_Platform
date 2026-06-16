"use client";

import type { MouseEvent, ReactNode } from "react";

import { NoteCardAiToggle } from "./NoteCardAiToggle";

type Props = {
  title: string;
  body: string;
  meta: string;
  ai: boolean;
  onClick: () => void;
  onToggleAi: (e: MouseEvent<HTMLButtonElement>) => void;
  menu?: ReactNode;
  emptyBodyLabel?: string;
};

export function NoteListCard({
  title,
  body,
  meta,
  ai,
  onClick,
  onToggleAi,
  menu,
  emptyBodyLabel = "Пустая заметка",
}: Props) {
  return (
    <div className="note-card" onClick={onClick}>
      <div className="note-card-body">
        <div className="note-card-page-head">
          <div className="note-card-title">{title}</div>
          {menu ? (
            <div className="chat-card-menu-slot" onClick={(e) => e.stopPropagation()}>
              {menu}
            </div>
          ) : null}
        </div>
        <div className="note-card-preview-post">{body || emptyBodyLabel}</div>
      </div>
      <div className="note-card-footer">
        <div className="note-card-footer-start">
          <NoteCardAiToggle ai={ai} onClick={onToggleAi} />
        </div>
        <span className="note-card-meta">{meta}</span>
      </div>
    </div>
  );
}
