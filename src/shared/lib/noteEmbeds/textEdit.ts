import { embedToken } from "@/shared/lib/noteEmbeds/bodyParse";
import { cloneLines, isTextLine } from "@/shared/lib/noteEmbeds/lines";
import type { BodyLine, CellPos } from "@/shared/lib/noteEmbeds/types";

/** Имя вложения из текста `[name]` или голого `name` в режиме редактирования. */
export function parseEmbedNameFromEditable(raw: string): string {
  const trimmed = raw.trim();
  const bracketed = trimmed.match(/^\[([^\]]*)\]$/);
  if (bracketed) return bracketed[1] ?? "";
  return trimmed;
}

export function updateEmbedCell(lines: BodyLine[], pos: CellPos, name: string): BodyLine[] {
  const next = cloneLines(lines);
  const cell = next[pos.line]?.cells[pos.cell];
  if (!cell || cell.type !== "embed") return lines;
  cell.name = name;
  return next;
}

export function updateTextCell(lines: BodyLine[], pos: CellPos, content: string): BodyLine[] {
  const next = cloneLines(lines);
  const line = next[pos.line];
  if (!line || !isTextLine(line) || line.cells[0]?.type !== "text") return lines;
  line.cells[0] = { type: "text", content };
  return next;
}

export function splitLineAtCaret(lines: BodyLine[], pos: CellPos, offset: number): BodyLine[] {
  const line = lines[pos.line];
  const cell = line?.cells[0];
  if (!line || !isTextLine(line) || cell?.type !== "text") return lines;

  const before = cell.content.slice(0, offset);
  const after = cell.content.slice(offset);
  const next = [
    ...lines.slice(0, pos.line),
    { cells: [{ type: "text" as const, content: before }] },
    { cells: [{ type: "text" as const, content: after }] },
    ...lines.slice(pos.line + 1),
  ];
  return next;
}

export function lineEditContent(line: BodyLine): string {
  return line.cells.map((c) => (c.type === "text" ? c.content : embedToken(c.name))).join("");
}

/** Строки edit-режима: одна textarea на строку body, токены `[file]` внутри текста. */
export function bodyToEditLines(body: string): BodyLine[] {
  if (!body) return [{ cells: [{ type: "text", content: "" }] }];
  return body.split("\n").map((content) => ({ cells: [{ type: "text", content }] }));
}
