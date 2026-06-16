import type { NoteFile } from "@/shared/types";
import type { CellPos } from "@/shared/lib/noteEmbeds";

export type NoteBodyEditorProps = {
  body: string;
  files: NoteFile[];
  isView: boolean;
  onBodyChange: (body: string) => void;
  onAddFile: (file: File) => NoteFile;
  onEditRequest?: () => void;
  focusRequest?: number;
};

export type ImageDropSlot = { line: number; slot: number };

export type CurrentDropTarget =
  | { type: "before"; before: CellPos }
  | { type: "imageSlot"; line: number; slot: number }
  | { type: "lineBefore"; line: number };
