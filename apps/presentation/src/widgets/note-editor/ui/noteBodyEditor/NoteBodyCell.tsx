"use client";

import {
  embedToken,
  findNoteFile,
  isImageEmbed,
  splitLineHighlightParts,
  type CellPos,
  type LineCell,
} from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

type BaseProps = {
  cell: LineCell;
  pos: CellPos;
  files: NoteFile[];
  isPlaceholder?: boolean;
  isDragLifted?: boolean;
  onEmbedPointerDown?: (pos: CellPos, e: React.PointerEvent) => void;
};

type ViewProps = BaseProps & {
  isView: true;
};

type EditProps = BaseProps & {
  isView: false;
  onTextChange: (content: string) => void;
  onTextEnter: (caret: number) => void;
};

type Props = ViewProps | EditProps;

export default function NoteBodyCell(props: Props) {
  const {
    cell,
    pos,
    files,
    isView,
    isPlaceholder = false,
    isDragLifted = false,
    onEmbedPointerDown,
  } = props;

  const dragHandlers = {
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
    },
  };

  if (cell.type === "text") {
    const parts = splitLineHighlightParts(cell.content);
    return (
      <span
        className={`note-body-cell note-body-cell--text${cell.content ? "" : " note-body-cell--empty"}`}
        data-line={pos.line}
        data-cell={pos.cell}
        {...dragHandlers}
      >
        <span className="note-body-text">
          {parts.length > 0
            ? parts.map((part, index) =>
                part.type === "embed" ? (
                  <span key={index} className="note-embed-token">
                    {part.value}
                  </span>
                ) : (
                  <span key={index}>{part.value}</span>
                ),
              )
            : "\u00a0"}
        </span>
      </span>
    );
  }

  const file = findNoteFile(files, cell.name);
  const isImage = isImageEmbed(file);
  const token = embedToken(cell.name);
  const blockLinkNativeDrag = (e: React.DragEvent) => e.preventDefault();
  const canPointerDrag = !isPlaceholder && onEmbedPointerDown != null;

  return (
    <span
      className={`note-body-cell note-body-cell--embed note-body-cell--embed-draggable${isPlaceholder ? " note-body-cell--drop-placeholder" : ""}${isDragLifted ? " note-body-cell--drag-lifted" : ""}`}
      data-line={pos.line}
      data-cell={pos.cell}
      data-embed-name={cell.name}
      style={canPointerDrag ? ({ touchAction: "none" } as const) : undefined}
      onPointerDown={
        canPointerDrag
          ? (e) => {
              onEmbedPointerDown!(pos, e);
            }
          : undefined
      }
      {...dragHandlers}
    >
      {isView && isImage && file?.url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="note-inline-image" src={file.url} alt={cell.name} draggable={false} />
      ) : (
        <span className="note-embed-chip note-embed-token">
          <a
            href={file?.url}
            target="_blank"
            rel="noopener noreferrer"
            draggable={false}
            onDragStart={blockLinkNativeDrag}
            onClick={(e) => !file?.url && e.preventDefault()}
          >
            {token}
          </a>
        </span>
      )}
    </span>
  );
}
