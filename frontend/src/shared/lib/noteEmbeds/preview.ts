import { isDropNoop, moveEmbedAt } from "@/shared/lib/noteEmbeds/embedMoves";
import { visibleEmbedIndices } from "@/shared/lib/noteEmbeds/imageGrid";
import { cloneLines, finalizeLines, isEmbedLine, isImageEmbedRow, isTextLine } from "@/shared/lib/noteEmbeds/lines";
import type { BodyLine, CellPos, NotePreviewItem, NotePreviewLine } from "@/shared/lib/noteEmbeds/types";
import type { NoteFile } from "@/shared/types";

function linesWithoutCell(lines: BodyLine[], at: CellPos, files: NoteFile[]): BodyLine[] {
  const next = cloneLines(lines);
  next[at.line]?.cells.splice(at.cell, 1);
  if (next[at.line]?.cells.length === 0) next.splice(at.line, 1);
  return finalizeLines(next, files);
}

function mapPreviewLines(
  displayLines: BodyLine[],
  placeholderName: string | null,
  files: NoteFile[],
): NotePreviewLine[] {
  let marked = false;
  return displayLines.map((line, li) => ({
    lineKey: `line-${li}`,
    isEmbed: isEmbedLine(line),
    isImageGrid: isImageEmbedRow(line, files),
    lineIndex: li,
    items: line.cells.map((cell, ci) => {
      const isPlaceholder =
        !!placeholderName &&
        !marked &&
        cell.type === "embed" &&
        cell.name === placeholderName;
      if (isPlaceholder) marked = true;
      return { kind: "cell" as const, cell, pos: { line: li, cell: ci }, isPlaceholder };
    }),
  }));
}

/** Превью = финальная раскладка после moveEmbedAt; перетаскиваемый элемент — невидимый placeholder. */
export function buildNotePreviewLines(
  lines: BodyLine[],
  dragFrom: CellPos | null,
  dropBefore: CellPos | null,
  files: NoteFile[],
): { lines: NotePreviewLine[]; trailingGap: boolean } {
  if (!dragFrom) {
    if (!dropBefore) {
      return {
        lines: lines.map((line, li) => ({
          lineKey: `line-${li}`,
          isEmbed: isEmbedLine(line),
          isImageGrid: isImageEmbedRow(line, files),
          lineIndex: li,
          items: line.cells.map((cell, ci) => ({ kind: "cell" as const, cell, pos: { line: li, cell: ci } })),
        })),
        trailingGap: false,
      };
    }

    const trailingGap = dropBefore.line === lines.length && dropBefore.cell === 0;
    const previewLines = lines.map((line, li) => {
      const items: NotePreviewItem[] = [];
      if (dropBefore.line === li && dropBefore.cell === 0) {
        items.push({ kind: "gap", key: `gap-line-${li}` });
      }
      if (isTextLine(line)) {
        line.cells.forEach((cell, ci) => {
          items.push({ kind: "cell", cell, pos: { line: li, cell: ci } });
        });
        return { lineKey: `line-${li}`, isEmbed: false, isImageGrid: false, lineIndex: li, items };
      }
      if (isImageEmbedRow(line, files)) {
        const slot =
          dropBefore.line === li
            ? visibleEmbedIndices(line, li, null).indexOf(dropBefore.cell)
            : -1;
        const insertSlot = slot >= 0 ? slot : line.cells.length;
        let visible = 0;
        for (let ci = 0; ci < line.cells.length; ci++) {
          if (visible === insertSlot) items.push({ kind: "gap", key: `gap-${li}-${insertSlot}` });
          items.push({ kind: "cell", cell: line.cells[ci]!, pos: { line: li, cell: ci } });
          visible += 1;
        }
        if (insertSlot >= line.cells.length) items.push({ kind: "gap", key: `gap-after-${li}` });
        return { lineKey: `line-${li}`, isEmbed: true, isImageGrid: true, lineIndex: li, items };
      }
      let gapAt = dropBefore.line === li ? dropBefore.cell : -1;
      let visible = 0;
      for (let ci = 0; ci < line.cells.length; ci++) {
        if (visible === gapAt) items.push({ kind: "gap", key: `gap-${li}-${gapAt}` });
        items.push({ kind: "cell", cell: line.cells[ci]!, pos: { line: li, cell: ci } });
        visible += 1;
      }
      if (dropBefore.line === li && dropBefore.cell === line.cells.length) {
        items.push({ kind: "gap", key: `gap-after-${li}` });
      }
      return { lineKey: `line-${li}`, isEmbed: true, isImageGrid: false, lineIndex: li, items };
    });
    return { lines: previewLines, trailingGap };
  }

  const src = lines[dragFrom.line]?.cells[dragFrom.cell];
  if (!src || src.type !== "embed") {
    return { lines: mapPreviewLines(lines, null, files), trailingGap: false };
  }

  if (!dropBefore || isDropNoop(dragFrom, dropBefore)) {
    return { lines: mapPreviewLines(linesWithoutCell(lines, dragFrom, files), null, files), trailingGap: false };
  }

  const displayLines = moveEmbedAt(lines, dragFrom, dropBefore, files);
  return { lines: mapPreviewLines(displayLines, src.name, files), trailingGap: false };
}
