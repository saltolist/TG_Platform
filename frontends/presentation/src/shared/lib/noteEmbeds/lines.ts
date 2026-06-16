import { embedToken, parseNoteBody } from "@/shared/lib/noteEmbeds/bodyParse";
import { findNoteFile, isImageEmbed } from "@/shared/lib/noteEmbeds/embedFiles";
import {
  MAX_IMAGES_PER_EMBED_ROW,
  type BodyLine,
  type LineCell,
  type NoteBodySegment,
} from "@/shared/lib/noteEmbeds/types";
import type { NoteFile } from "@/shared/types";

export function isTextLine(line: BodyLine): boolean {
  return line.cells.length > 0 && line.cells.every((c) => c.type === "text");
}

export function isEmbedLine(line: BodyLine): boolean {
  return line.cells.length > 0 && line.cells.every((c) => c.type === "embed");
}

export function isImageEmbedRow(line: BodyLine, files: NoteFile[]): boolean {
  if (!isEmbedLine(line)) return false;
  return line.cells.some((c) => c.type === "embed" && isImageEmbed(findNoteFile(files, c.name)));
}

/** Текстовые и embed-строки всегда разделены: в одной строке не смешиваются. */
export function segmentsToLines(segments: NoteBodySegment[]): BodyLine[] {
  const lines: BodyLine[] = [];
  let embedBuf: LineCell[] = [];

  const flushEmbeds = () => {
    if (embedBuf.length > 0) {
      lines.push({ cells: embedBuf });
      embedBuf = [];
    }
  };

  for (const seg of segments) {
    if (seg.type === "embed") {
      embedBuf.push({ type: "embed", name: seg.name });
      continue;
    }
    flushEmbeds();
    if (!seg.content) {
      lines.push({ cells: [{ type: "text", content: "" }] });
      continue;
    }
    for (const part of seg.content.split("\n")) {
      lines.push({ cells: [{ type: "text", content: part }] });
    }
  }
  flushEmbeds();
  return lines.length > 0 ? lines : [{ cells: [{ type: "text", content: "" }] }];
}

export function linesToBody(lines: BodyLine[]): string {
  if (!lines.length) return "";
  return lines
    .map((line) => line.cells.map((c) => (c.type === "text" ? c.content : embedToken(c.name))).join(""))
    .join("\n");
}

/** Единый формат body для сравнения и сохранения (разделяет текст и вложения по строкам). */
export function canonicalNoteBody(body: string): string {
  return linesToBody(segmentsToLines(parseNoteBody(body)));
}

export function countEmbedRowImages(cells: LineCell[], files: NoteFile[]): number {
  return cells.filter((c) => c.type === "embed" && isImageEmbed(findNoteFile(files, c.name))).length;
}

function splitEmbedCellsToRows(cells: LineCell[], files: NoteFile[]): BodyLine[] {
  const rows: BodyLine[] = [];
  let buf: LineCell[] = [];
  let imageCount = 0;

  for (const cell of cells) {
    if (cell.type !== "embed") {
      buf.push(cell);
      continue;
    }
    const isImg = isImageEmbed(findNoteFile(files, cell.name));
    if (isImg && imageCount >= MAX_IMAGES_PER_EMBED_ROW) {
      if (buf.length) rows.push({ cells: buf });
      buf = [cell];
      imageCount = 1;
    } else {
      buf.push(cell);
      if (isImg) imageCount += 1;
    }
  }
  if (buf.length) rows.push({ cells: buf });
  return rows;
}

export function normalizeEmbedImageRows(lines: BodyLine[], files: NoteFile[]): BodyLine[] {
  return lines.flatMap((line) => (isEmbedLine(line) ? splitEmbedCellsToRows(line.cells, files) : [line]));
}

export function normalizeNoteBody(body: string, files: NoteFile[]): string {
  return linesToBody(normalizeEmbedImageRows(segmentsToLines(parseNoteBody(body)), files));
}

export function cloneLines(lines: BodyLine[]): BodyLine[] {
  return lines.map((l) => ({ cells: [...l.cells] }));
}

function splitMixedLine(line: BodyLine): BodyLine[] {
  const hasText = line.cells.some((c) => c.type === "text");
  const hasEmbed = line.cells.some((c) => c.type === "embed");
  if (!hasText || !hasEmbed) return [line];

  const out: BodyLine[] = [];
  let embedBuf: LineCell[] = [];
  for (const cell of line.cells) {
    if (cell.type === "text") {
      if (embedBuf.length) {
        out.push({ cells: embedBuf });
        embedBuf = [];
      }
      out.push({ cells: [cell] });
    } else {
      embedBuf.push(cell);
    }
  }
  if (embedBuf.length) out.push({ cells: embedBuf });
  return out;
}

export function finalizeLines(lines: BodyLine[], files: NoteFile[]): BodyLine[] {
  const split = lines.flatMap(splitMixedLine);
  const withEmbeds = normalizeEmbedImageRows(split, files);
  const next = withEmbeds
    .map((line) => ({
      cells: line.cells.length > 0 ? line.cells : [{ type: "text" as const, content: "" }],
    }))
    .filter((line) => line.cells.some((c) => (c.type === "text" ? c.content.length > 0 : true)));
  return next.length > 0 ? next : [{ cells: [{ type: "text", content: "" }] }];
}
