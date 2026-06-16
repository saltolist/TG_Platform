"use client";

import { useCallback, useMemo, useRef } from "react";
import {
  linesToBody,
  normalizeEmbedImageRows,
  parseNoteBody,
  segmentsToLines,
  type BodyLine,
} from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

type Params = {
  body: string;
  files: NoteFile[];
  onBodyChange: (body: string) => void;
};

export function useNoteBodyLines({ body, files, onBodyChange }: Params) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const linesRef = useRef<BodyLine[]>([]);
  const filesRef = useRef<NoteFile[]>(files);
  const bodyRef = useRef(body);
  bodyRef.current = body;

  const lines = useMemo(
    () => normalizeEmbedImageRows(segmentsToLines(parseNoteBody(body)), files),
    [body, files],
  );
  linesRef.current = lines;
  filesRef.current = files;

  const applyLines = useCallback(
    (next: BodyLine[]) => {
      onBodyChange(linesToBody(next));
    },
    [onBodyChange],
  );

  const hasContent = lines.some((l) =>
    l.cells.some((c) => (c.type === "text" ? c.content.trim() : true)),
  );

  return {
    canvasRef,
    linesRef,
    filesRef,
    bodyRef,
    lines,
    files,
    applyLines,
    hasContent,
  };
}
