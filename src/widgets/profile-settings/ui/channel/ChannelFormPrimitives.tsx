"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { MessageTrashIcon } from "@/entities/message";
import { useProfileTextareaAutoResize } from "@/shared/lib/use-profile-textarea-auto-resize";
import { useFitTitleSize } from "@/shared/lib/use-fit-title";

export function ChannelSubsection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="profile-channel-subsection">
      <div className="profile-subsection-title">{title}</div>
      {children}
    </div>
  );
}

export function Area({
  label,
  value,
  onChange,
  active = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  active?: boolean;
}) {
  const { ref: textareaRef, resize } = useProfileTextareaAutoResize(value, active);

  return (
    <label className="profile-row">
      <span className="profile-label">{label}</span>
      <textarea
        ref={textareaRef}
        className="profile-input profile-input-explicit profile-textarea profile-textarea-compact"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          requestAnimationFrame(resize);
        }}
      />
    </label>
  );
}

export function RubricNoteFields({
  title,
  description,
  onTitleChange,
  onDescriptionChange,
  onRemove,
  canRemove,
}: {
  title: string;
  description: string;
  onTitleChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  useFitTitleSize(titleRef, title, true, { maxSize: 18, minSize: 13 });

  const resizeDescription = () => {
    const textarea = descriptionRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  };

  useLayoutEffect(() => {
    resizeDescription();
  }, [description]);

  const focusDescription = () => {
    const textarea = descriptionRef.current;
    if (!textarea) return;
    textarea.focus();
    const end = textarea.value.length;
    textarea.setSelectionRange(end, end);
  };

  return (
    <div className="rubric-note-fields">
      <div className="rubric-note-title-row">
        <textarea
          ref={titleRef}
          className="rubric-note-title"
          rows={1}
          placeholder="Название"
          value={title}
          onChange={(e) => {
            onTitleChange(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            focusDescription();
          }}
        />
        <button
          className="rubric-note-delete"
          disabled={!canRemove}
          onClick={onRemove}
          type="button"
          aria-label="Удалить рубрику"
          title={canRemove ? "Удалить рубрику" : "Нельзя удалить последнюю рубрику"}
        >
          <MessageTrashIcon />
        </button>
      </div>
      <div className="rubric-note-divider" />
      <textarea
        ref={descriptionRef}
        className="rubric-note-description"
        rows={5}
        placeholder="Описание"
        value={description}
        onChange={(e) => {
          onDescriptionChange(e.target.value);
          requestAnimationFrame(resizeDescription);
        }}
      />
    </div>
  );
}
