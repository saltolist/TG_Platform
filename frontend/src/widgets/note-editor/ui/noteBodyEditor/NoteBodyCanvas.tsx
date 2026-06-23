"use client";

import type { NoteFile } from "@/shared/types";

import NoteMarkdownRenderer from "@/widgets/note-editor/ui/NoteMarkdownRenderer";
import NoteBlockEditor from "./NoteBlockEditorDynamic";

type Props = {
  body: string;
  files: NoteFile[];
  isView: boolean;
  onBodyChange: (body: string) => void;
  onAddFile: (file: File) => NoteFile;
  focusRequest?: number;
};

export default function NoteBodyCanvas({
  body,
  files,
  isView,
  onBodyChange,
  onAddFile,
  focusRequest,
}: Props) {
  if (!isView) {
    return (
      <NoteBlockEditor
        body={body}
        files={files}
        onBodyChange={onBodyChange}
        onAddFile={onAddFile}
        focusRequest={focusRequest}
      />
    );
  }

  return <NoteMarkdownRenderer body={body} files={files} />;
}
