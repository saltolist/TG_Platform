import type { NoteFile } from "@/shared/types";

export type NoteBodyEditorProps = {
  body: string;
  files: NoteFile[];
  isView: boolean;
  onBodyChange: (body: string) => void;
  onAddFile: (file: File) => NoteFile;
  onEditRequest?: () => void;
  focusRequest?: number;
};
