"use client";

import { useRef } from "react";

import { useNoteBodyViewMode } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyViewMode";
import NoteBodyCanvas from "@/widgets/note-editor/ui/noteBodyEditor/NoteBodyCanvas";
import type { NoteBodyEditorProps } from "@/widgets/note-editor/ui/noteBodyEditor/types";

export default function NoteBodyEditor(props: NoteBodyEditorProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const viewMode = useNoteBodyViewMode({
    canvasRef,
    isView: props.isView,
    onEditRequest: props.onEditRequest,
  });

  return (
    <div
      ref={canvasRef}
      className={`note-body-canvas${props.isView ? " note-body-view note-body-view--rich" : " note-body-edit-canvas"}`}
      onDoubleClick={props.isView ? viewMode.handleViewDoubleClick : undefined}
    >
      <NoteBodyCanvas
        body={props.body}
        files={props.files}
        isView={props.isView}
        onBodyChange={props.onBodyChange}
        onAddFile={props.onAddFile}
        focusRequest={props.focusRequest}
      />
    </div>
  );
}
