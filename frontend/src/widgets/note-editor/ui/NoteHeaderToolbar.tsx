"use client";

type Props = {
  onSave?: () => void;
  onCancel?: () => void;
  saveDisabled?: boolean;
  showCancel?: boolean;
};

export default function NoteHeaderToolbar({
  onSave,
  onCancel,
  saveDisabled = true,
  showCancel = false,
}: Props) {
  return (
    <div className="note-ctrl">
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
