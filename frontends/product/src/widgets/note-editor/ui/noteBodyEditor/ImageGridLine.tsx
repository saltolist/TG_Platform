"use client";

import {
  buildImageGridSlotLayout,
  type BodyLine,
  type CellPos,
} from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";
import NoteBodyCell from "./NoteBodyCell";
import NoteBodyDropIndicator from "./NoteBodyDropIndicator";
import type { ImageDropSlot } from "./types";

type Props = {
  line: BodyLine;
  lineIndex: number;
  lines: BodyLine[];
  files: NoteFile[];
  isView: boolean;
  dragFrom: CellPos | null;
  imageDropSlot: ImageDropSlot | null;
  dropSlotBefore: boolean;
  onEmbedPointerDown?: (pos: CellPos, e: React.PointerEvent) => void;
};

export default function ImageGridLine({
  line,
  lineIndex,
  lines,
  files,
  isView,
  dragFrom,
  imageDropSlot,
  dropSlotBefore,
  onEmbedPointerDown,
}: Props) {
  const insertSlot = imageDropSlot?.line === lineIndex ? imageDropSlot.slot : null;

  const incoming =
    dragFrom != null && dragFrom.line !== lineIndex && lines[dragFrom.line]?.cells[dragFrom.cell]?.type === "embed"
      ? lines[dragFrom.line]!.cells[dragFrom.cell]!
      : null;

  const slots = buildImageGridSlotLayout(
    line,
    lineIndex,
    dragFrom,
    insertSlot,
    files,
    incoming,
    incoming ? dragFrom : null,
  );

  return (
    <div
      className="note-body-line note-body-line--embed note-embed-image-grid"
      data-line={lineIndex}
      onDragOver={(e) => e.preventDefault()}
    >
      {dropSlotBefore ? (
        <div className="note-embed-grid-drop-lead-abs" aria-hidden>
          <NoteBodyDropIndicator axis="horizontal" />
        </div>
      ) : null}
      {slots.map((item, slotIdx) =>
        item ? (
          isView ? (
            <NoteBodyCell
              key={`ig-${lineIndex}-${slotIdx}`}
              cell={item.cell}
              pos={item.pos}
              files={files}
              isView
              isPlaceholder={item.isPlaceholder}
              onEmbedPointerDown={onEmbedPointerDown}
              isDragLifted={
                !item.isPlaceholder &&
                dragFrom != null &&
                dragFrom.line === lineIndex &&
                dragFrom.cell === item.pos.cell
              }
            />
          ) : (
            <NoteBodyCell
              key={`ig-${lineIndex}-${slotIdx}`}
              cell={item.cell}
              pos={item.pos}
              files={files}
              isView={false}
              isPlaceholder={item.isPlaceholder}
              onTextChange={() => {}}
              onTextEnter={() => {}}
              onEmbedPointerDown={onEmbedPointerDown}
              isDragLifted={
                !item.isPlaceholder &&
                dragFrom != null &&
                dragFrom.line === lineIndex &&
                dragFrom.cell === item.pos.cell
              }
            />
          )
        ) : (
          <div
            key={`empty-${lineIndex}-${slotIdx}`}
            className="note-embed-image-slot note-embed-image-slot--empty"
            aria-hidden
          />
        ),
      )}
    </div>
  );
}
