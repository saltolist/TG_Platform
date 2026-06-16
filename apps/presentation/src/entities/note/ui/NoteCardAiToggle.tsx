"use client";

import { useState, type MouseEvent } from "react";

import { BrainIcon } from "@/shared/ui/model-picker";

type Props = {
  ai: boolean;
  onClick: (e: MouseEvent<HTMLButtonElement>) => void;
};

export function NoteCardAiToggle({ ai, onClick }: Props) {
  const [suppressHover, setSuppressHover] = useState(false);

  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={ai}
      className={`note-card-context-control${suppressHover ? " note-card-context-control--suppress-hover" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        onClick(e);
        setSuppressHover(true);
        e.currentTarget.blur();
      }}
      onMouseLeave={() => setSuppressHover(false)}
      aria-label={ai ? "Заметка в контексте" : "Заметка не в контексте"}
    >
      <span
        className={`note-ai-toggle${ai ? " on" : " off"}${suppressHover ? " note-ai-toggle--suppress-hover" : ""}`}
        aria-hidden
      >
        <BrainIcon />
      </span>
      <span className={`note-card-context-label${ai ? "" : " note-card-context-label--out"}`}>
        {ai ? "В контексте" : "Не в контексте"}
      </span>
    </button>
  );
}
