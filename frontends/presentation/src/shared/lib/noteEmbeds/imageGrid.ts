import { isImageEmbedRow } from "@/shared/lib/noteEmbeds/lines";
import {
  MAX_IMAGES_PER_EMBED_ROW,
  type BodyLine,
  type CellPos,
  type ImageGridSlotItem,
  type LineCell,
} from "@/shared/lib/noteEmbeds/types";
import type { NoteFile } from "@/shared/types";

export function visibleEmbedIndices(line: BodyLine, lineIndex: number, dragFrom: CellPos | null): number[] {
  const indices: number[] = [];
  for (let ci = 0; ci < line.cells.length; ci++) {
    if (dragFrom?.line === lineIndex && dragFrom.cell === ci) continue;
    indices.push(ci);
  }
  return indices;
}

/** Слот 0..3 (3 = в конец ряда) → dropBefore.cell в исходной строке. */
export function imageGridSlotToDropBefore(
  line: BodyLine,
  lineIndex: number,
  slot: number,
  dragFrom: CellPos | null,
): CellPos {
  const indices = visibleEmbedIndices(line, lineIndex, dragFrom);
  if (slot <= 0) return { line: lineIndex, cell: indices[0] ?? 0 };
  if (slot >= indices.length) return { line: lineIndex, cell: line.cells.length };
  return { line: lineIndex, cell: indices[slot]! };
}

export function dropBeforeToImageSlot(
  line: BodyLine,
  lineIndex: number,
  before: CellPos,
  dragFrom: CellPos | null,
): number {
  const indices = visibleEmbedIndices(line, lineIndex, dragFrom);
  const idx = indices.indexOf(before.cell);
  return idx >= 0 ? idx : indices.length;
}

function orderedSlotsWithPlaceholder(
  others: { cell: LineCell; ci: number }[],
  src: LineCell,
  placeholderPos: CellPos,
  rowLineIndex: number,
  targetSlot: number,
): ImageGridSlotItem[] {
  const ordered: ImageGridSlotItem[] = [];
  const slot = Math.max(0, Math.min(MAX_IMAGES_PER_EMBED_ROW, targetSlot));
  for (let i = 0; i < others.length; i++) {
    if (ordered.length === slot) {
      ordered.push({ cell: src, pos: placeholderPos, isPlaceholder: true });
    }
    ordered.push({
      cell: others[i]!.cell,
      pos: { line: rowLineIndex, cell: others[i]!.ci },
      isPlaceholder: false,
    });
  }
  if (ordered.length === slot) {
    ordered.push({ cell: src, pos: placeholderPos, isPlaceholder: true });
  }
  return ordered;
}

/** Раскладка 3 фиксированных слотов; при DnD — placeholder в insertSlot, без finalizeLines. */
export function buildImageGridSlotLayout(
  line: BodyLine,
  lineIndex: number,
  dragFrom: CellPos | null,
  insertSlot: number | null,
  files: NoteFile[],
  /** Embed с другой строки — показываем placeholder в этой сетке при наведении. */
  incomingEmbed: LineCell | null,
  incomingFrom: CellPos | null,
): (ImageGridSlotItem | null)[] {
  const slots: (ImageGridSlotItem | null)[] = [null, null, null];
  if (!isImageEmbedRow(line, files)) return slots;

  const draggingHere = dragFrom?.line === lineIndex;
  const srcLocal =
    draggingHere && line.cells[dragFrom.cell]?.type === "embed" ? line.cells[dragFrom.cell]! : null;

  const showIncoming =
    !draggingHere &&
    incomingEmbed?.type === "embed" &&
    insertSlot != null &&
    incomingFrom != null;

  if (showIncoming) {
    const others: { cell: LineCell; ci: number }[] = line.cells.map((cell, ci) => ({ cell, ci }));
    /** Слоты 2 и 3 при неполном ряду — одна и та же позиция «в конец»; иначе плейсхолдер то появляется, то пропадает и границы колонок дрожат. */
    const insertCap = Math.min(insertSlot!, others.length);
    const ordered = orderedSlotsWithPlaceholder(
      others,
      incomingEmbed,
      incomingFrom,
      lineIndex,
      insertCap,
    );
    ordered.forEach((item, i) => {
      if (i < MAX_IMAGES_PER_EMBED_ROW) slots[i] = item;
    });
    return slots;
  }

  if (!draggingHere || !srcLocal) {
    line.cells.forEach((cell, ci) => {
      if (ci < MAX_IMAGES_PER_EMBED_ROW) {
        slots[ci] = { cell, pos: { line: lineIndex, cell: ci }, isPlaceholder: false };
      }
    });
    return slots;
  }

  const others: { cell: LineCell; ci: number }[] = [];
  line.cells.forEach((cell, ci) => {
    if (ci === dragFrom.cell) return;
    others.push({ cell, ci });
  });

  const othersCount = others.length;
  const rawInsert = insertSlot ?? dragFrom.cell;
  const targetSlot = Math.min(
    Math.max(0, Math.min(MAX_IMAGES_PER_EMBED_ROW, rawInsert)),
    othersCount,
  );

  const ordered = orderedSlotsWithPlaceholder(others, srcLocal, dragFrom, lineIndex, targetSlot);

  ordered.forEach((item, i) => {
    if (i < MAX_IMAGES_PER_EMBED_ROW) slots[i] = item;
  });
  return slots;
}
