"use client";

import {
  NOTE_HEADER_ICON_STROKE_MODE,
  NoteIconAttach,
  NoteIconEdit,
  NoteIconPreview,
} from "@/shared/ui/icons/note-header-icons";

type Props = {
  mode: "view" | "edit";
  onToggleMode?: () => void;
  onAttach?: () => void;
  onSave?: () => void;
  onCancel?: () => void;
  saveDisabled?: boolean;
  showCancel?: boolean;
  showAttach?: boolean;
  showModeToggle?: boolean;
};

export default function NoteHeaderToolbar({
  mode,
  onToggleMode,
  onAttach,
  onSave,
  onCancel,
  saveDisabled = true,
  showCancel = false,
  showAttach = false,
  showModeToggle = true,
}: Props) {
  return (
    <div className="note-ctrl">
      {showAttach && onAttach ? (
        <button
          className="note-header-plain-btn note-header-plain-btn--sm note-header-plain-btn--attach"
          onClick={onAttach}
          type="button"
          title="Прикрепить файл"
          aria-label="Прикрепить файл"
        >
          <NoteIconAttach />
        </button>
      ) : null}
      {showModeToggle && onToggleMode ? (
        <button
          className="note-header-plain-btn note-header-plain-btn--mode"
          onClick={onToggleMode}
          type="button"
          title={mode === "view" ? "Редактировать" : "Просмотр"}
          aria-label={mode === "view" ? "Редактировать" : "Просмотр"}
        >
          {mode === "view" ? (
            <NoteIconEdit strokeWidth={NOTE_HEADER_ICON_STROKE_MODE} />
          ) : (
            <NoteIconPreview strokeWidth={NOTE_HEADER_ICON_STROKE_MODE} />
          )}
        </button>
      ) : null}
      <button
        className="btn btn-ghost btn-sm note-header-save"
        onClick={onSave}
        disabled={saveDisabled}
        type="button"
      >
        Сохранить
      </button>
      {showCancel && onCancel ? (
        <button className="btn btn-ghost btn-sm" onClick={onCancel} type="button">
          Отменить
        </button>
      ) : null}
    </div>
  );
}
