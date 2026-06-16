"use client";

import type { BodyLine, CellPos } from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

import NoteBodyDocumentEdit from "./NoteBodyDocumentEdit";
import NoteBodyDocumentView from "./NoteBodyDocumentView";
import type { ImageDropSlot } from "./types";

type Props = {
  body: string;
  lines: BodyLine[];
  files: NoteFile[];
  isView: boolean;
  hasContent: boolean;
  dragFrom: CellPos | null;
  dropBefore: CellPos | null;
  imageDropSlot: ImageDropSlot | null;
  dropLineBefore: number | null;
  dropGapActive: boolean;
  dropLineBeforeActive: boolean;
  onBodyChange: (body: string) => void;
  applyLines: (next: BodyLine[]) => void;
  onTextEnter: (pos: CellPos, offset: number) => void;
  onEmbedPointerDown: (pos: CellPos, e: React.PointerEvent, line?: BodyLine, lineIndex?: number) => void;
};

export default function NoteBodyCanvas({
  body,
  lines,
  files,
  isView,
  hasContent,
  dragFrom,
  dropBefore,
  imageDropSlot,
  dropLineBefore,
  dropGapActive,
  dropLineBeforeActive,
  onBodyChange,
  applyLines,
  onTextEnter,
  onEmbedPointerDown,
}: Props) {
  if (!isView) {
    return <NoteBodyDocumentEdit body={body} onChange={onBodyChange} />;
  }

  return (
    <NoteBodyDocumentView
      lines={lines}
      files={files}
      hasContent={hasContent}
      dragFrom={dragFrom}
      dropBefore={dropBefore}
      imageDropSlot={imageDropSlot}
      dropLineBefore={dropLineBefore}
      dropGapActive={dropGapActive}
      dropLineBeforeActive={dropLineBeforeActive}
      applyLines={applyLines}
      onTextEnter={onTextEnter}
      onEmbedPointerDown={onEmbedPointerDown}
    />
  );
}
