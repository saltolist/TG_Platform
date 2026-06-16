"use client";

import { embedToken, findNoteFile, isImageEmbed, type LineCell } from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

type Props = { cell: LineCell; files: NoteFile[] };

export default function NoteEmbedDragPreview({ cell, files }: Props) {
  if (cell.type !== "embed") return null;
  const file = findNoteFile(files, cell.name);
  const isImage = isImageEmbed(file);
  const token = embedToken(cell.name);
  return (
    <div className="note-embed-drag-float-inner">
      {isImage && file?.url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={file.url} alt="" className="note-embed-drag-float-img" draggable={false} />
      ) : (
        <code className="note-embed-drag-float-code">{token}</code>
      )}
    </div>
  );
}
