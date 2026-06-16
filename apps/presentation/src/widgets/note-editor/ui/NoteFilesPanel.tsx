"use client";

import type { NoteFile } from "@/shared/types";
import { isNoteImageFile } from "@/shared/lib/noteDraft";
import { NoteIconImage } from "@/shared/ui/icons/note-header-icons";

const EMBED_MIME = "application/x-note-embed";

function NoteFileItemIcon({ file }: { file: NoteFile }) {
  if (isNoteImageFile(file)) {
    return (
      <span className="note-file-item-icon">
        <NoteIconImage />
      </span>
    );
  }
  return <span className="note-file-item-icon note-file-item-icon--attach">📎</span>;
}

type Props = {
  files: NoteFile[];
  draggable?: boolean;
};

export default function NoteFilesPanel({ files, draggable = false }: Props) {
  if (!files.length) return null;
  return (
    <div className="note-files">
      <div className="note-files-label">Вложения</div>
      <p className="note-files-hint">Перетащите в текст заметки — в разметке появится [имя файла]</p>
      {files.map((f, i) => {
        const label = (
          <>
            <NoteFileItemIcon file={f} />
            <b>{f.name}</b>
            <span>({f.type || "file"})</span>
          </>
        );
        const dragProps = draggable
          ? {
              draggable: true,
              onDragStart: (e: React.DragEvent) => {
                e.dataTransfer.setData(EMBED_MIME, f.name);
                e.dataTransfer.setData("text/plain", `[${f.name}]`);
                e.dataTransfer.effectAllowed = "copy";
              },
            }
          : {};
        return f.url ? (
          <a
            key={i}
            className="note-file-item note-file-item--draggable"
            href={f.url}
            target="_blank"
            rel="noopener noreferrer"
            {...dragProps}
          >
            {label}
          </a>
        ) : (
          <div key={i} className="note-file-item note-file-item--draggable" {...dragProps}>
            {label}
          </div>
        );
      })}
    </div>
  );
}
