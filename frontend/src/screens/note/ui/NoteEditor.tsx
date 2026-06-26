"use client";

import dynamic from "next/dynamic";
import { useRef } from "react";

import { NoteHeaderToolbar } from "@/widgets/note-editor";
import { useNoteEditor } from "@/screens/note/model/useNoteEditor";
import type { ActiveNote } from "@/shared/types";
import { formatStoredDate } from "@/shared/lib/helpers";
import { noteIdentityKey } from "@/shared/lib/noteDraft";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";

const NoteBlockNote = dynamic(() => import("@/widgets/note-editor/ui/NoteBlockNote"), {
  ssr: false,
});

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
            onSave={editor.save}
            onCancel={editor.cancel}
            saveDisabled={!editor.changed}
            showCancel={editor.changed}
          />
        </div>
        <div className="note-shell-content">
          <NoteBlockNote
            key={`${noteIdentityKey(note)}:${editor.editorResetKey}`}
            doc={editor.doc}
            body={editor.body}
            files={editor.files}
            getFiles={editor.getFiles}
            onChange={editor.setContent}
            onUploadFile={editor.addFile}
            focusRequest={editor.bodyFocusRequest}
          />
        </div>
      </div>
      <div className="note-timestamps">
        Создана: {formatStoredDate(note.date)} &nbsp;•&nbsp; Изменена:{" "}
        {editor.changed ? "сейчас" : formatStoredDate(note.date)}
      </div>
    </div>
  );
}
