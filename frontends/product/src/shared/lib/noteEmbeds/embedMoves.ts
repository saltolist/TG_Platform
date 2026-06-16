import { embedToken } from "@/shared/lib/noteEmbeds/bodyParse";
import { cloneLines, finalizeLines, isTextLine } from "@/shared/lib/noteEmbeds/lines";
import type { BodyLine, CellPos, LineCell } from "@/shared/lib/noteEmbeds/types";
import type { NoteFile } from "@/shared/types";

function adjustBeforeAfterRemoval(from: CellPos, before: CellPos, sourceLineRemoved: boolean): CellPos {
  let { line, cell } = before;
  if (sourceLineRemoved && from.line < line) line -= 1;
  else if (from.line === line && from.cell < cell) cell -= 1;
  return { line: Math.max(0, line), cell: Math.max(0, cell) };
}

export function isDropNoop(from: CellPos, before: CellPos): boolean {
  return from.line === before.line && (from.cell === before.cell || from.cell + 1 === before.cell);
}

export function insertEmbedInBody(body: string, offset: number, name: string): string {
  const token = embedToken(name);
  const pos = Math.max(0, Math.min(offset, body.length));
  return body.slice(0, pos) + token + body.slice(pos);
}

export function moveEmbedAt(lines: BodyLine[], from: CellPos, before: CellPos, files: NoteFile[]): BodyLine[] {
  const src = lines[from.line]?.cells[from.cell];
  if (!src || src.type !== "embed") return lines;
  if (isDropNoop(from, before)) return lines;

  const next = cloneLines(lines);
  next[from.line].cells.splice(from.cell, 1);
  const sourceLineRemoved = next[from.line].cells.length === 0;
  if (sourceLineRemoved) next.splice(from.line, 1);

  const at = adjustBeforeAfterRemoval(from, before, sourceLineRemoved);
  const target = next[at.line];

  if (!target || isTextLine(target)) {
    next.splice(at.line, 0, { cells: [src] });
    return finalizeLines(next, files);
  }

  target.cells.splice(Math.min(at.cell, target.cells.length), 0, src);
  return finalizeLines(next, files);
}

export function moveEmbedToImageGridSlot(
  lines: BodyLine[],
  from: CellPos,
  targetLineIndex: number,
  slot: number,
  files: NoteFile[],
): BodyLine[] {
  const src = lines[from.line]?.cells[from.cell];
  if (!src || src.type !== "embed") return lines;

  const next = cloneLines(lines);
  next[from.line].cells.splice(from.cell, 1);
  const sourceLineRemoved = next[from.line].cells.length === 0;
  if (sourceLineRemoved) next.splice(from.line, 1);

  const adjustedLine = sourceLineRemoved && from.line < targetLineIndex ? targetLineIndex - 1 : targetLineIndex;
  const targetLine = Math.max(0, Math.min(adjustedLine, next.length));
  const target = next[targetLine];

  if (!target || isTextLine(target)) {
    next.splice(targetLine, 0, { cells: [src] });
    return finalizeLines(next, files);
  }

  target.cells.splice(Math.max(0, Math.min(slot, target.cells.length)), 0, src);
  return finalizeLines(next, files);
}

export function moveEmbedToLineBefore(lines: BodyLine[], from: CellPos, lineIndex: number, files: NoteFile[]): BodyLine[] {
  const src = lines[from.line]?.cells[from.cell];
  if (!src || src.type !== "embed") return lines;

  const next = cloneLines(lines);
  next[from.line].cells.splice(from.cell, 1);
  const removedSourceLine = next[from.line]?.cells.length === 0;
  if (removedSourceLine) next.splice(from.line, 1);

  const adjustedLine = removedSourceLine && from.line < lineIndex ? lineIndex - 1 : lineIndex;
  const targetLine = Math.max(0, Math.min(adjustedLine, next.length));
  next.splice(targetLine, 0, { cells: [src] });
  return finalizeLines(next, files);
}

export function insertEmbedAt(lines: BodyLine[], before: CellPos, name: string, files: NoteFile[]): BodyLine[] {
  const next = cloneLines(lines);
  const line = Math.min(before.line, next.length);
  const target = next[line];
  const embed: LineCell = { type: "embed", name };

  if (!target || isTextLine(target)) {
    next.splice(line, 0, { cells: [embed] });
    return finalizeLines(next, files);
  }

  target.cells.splice(Math.min(before.cell, target.cells.length), 0, embed);
  return finalizeLines(next, files);
}
