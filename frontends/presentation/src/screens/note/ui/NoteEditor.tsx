"use client";

import { useRef } from "react";
import { NoteBodyEditor, NoteFilesPanel, NoteHeaderToolbar } from "@/widgets/note-editor";
import { useNoteEditor } from "@/screens/note/model/useNoteEditor";
import type { ActiveNote } from "@/shared/types";
import { formatStoredDate } from "@/shared/lib/helpers";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";

export default function NoteEditor({ note }: { note: ActiveNote }) {
  const editor = useNoteEditor(note);
  const scopeRef = useRef<HTMLDivElement | null>(null);

  useModSaveUndo({ dirty: editor.changed, onSave: editor.save, scopeRef });

  return (
    <div className="note-layout">
      <div className="note-shell" ref={scopeRef}>
        <div className="note-shell-header">
          <div className="note-title-block">
            <div className="note-title-row">
              <textarea
                ref={editor.titleRef}
                className="note-title-edit"
                rows={1}
                placeholder="Без названия"
                value={editor.title}
                onChange={(e) => editor.setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  editor.focusBodyFromTitle();
                }}
              />
            </div>
          </div>
          <NoteHeaderToolbar
            mode={editor.isView ? "view" : "edit"}
            showAttach={!editor.isView}
            onAttach={() => editor.fileInputRef.current?.click()}
            showModeToggle
            onToggleMode={editor.isView ? editor.setEditMode : editor.setViewMode}
            onSave={editor.save}
            onCancel={editor.cancel}
            saveDisabled={!editor.changed}
            showCancel={editor.changed}
          />
        </div>
        <div className="note-shell-content">
          <NoteBodyEditor
            body={editor.body}
            files={editor.files}
            isView={editor.isView}
            onBodyChange={editor.setBody}
            onAddFile={editor.addFile}
            onEditRequest={editor.setEditMode}
            focusRequest={editor.bodyFocusRequest}
          />
          <NoteFilesPanel files={editor.files} draggable />
        </div>
      </div>
      <div className="note-timestamps">
        Создана: {formatStoredDate(note.date)} &nbsp;•&nbsp; Изменена:{" "}
        {editor.changed ? "сейчас" : formatStoredDate(note.date)}
      </div>
      {!editor.isView ? (
        <input
          type="file"
          ref={editor.fileInputRef}
          style={{ display: "none" }}
          onChange={editor.onFilePicked}
        />
      ) : null}
    </div>
  );
}
