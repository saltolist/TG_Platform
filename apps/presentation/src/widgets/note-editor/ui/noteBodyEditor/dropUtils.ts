import type { MutableRefObject } from "react";
import {
  EMBED_IMAGE_SLOT_GAP,
  isEmbedLine,
  isImageEmbedRow,
  isTextLine,
  MAX_IMAGES_PER_EMBED_ROW,
  type BodyLine,
  type CellPos,
} from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";
import {
  FLEX_DROP_X_HYST_PX,
  IMAGE_GRID_BOTTOM_SIDE_DROP_TOLERANCE_PX,
  TEXT_DROP_BOUNDARY_FRAC,
} from "./constants";
import type { ImageDropSlot } from "./types";

/**
 * Гистерезис по Y между «вставить перед строкой i» и «после неё».
 * Шире — меньше дрожания у середины строки при появлении индикатора дропа.
 */
export function textLineDropHysteresisPx(lineHeight: number): number {
  return Math.max(28, lineHeight * 0.28);
}

/** Метрики текста без учёта in-flow индикаторов дропа (они вынесены в absolute). */
export function textLineCellMetrics(lineEl: HTMLElement): { top: number; height: number } {
  const cell = lineEl.querySelector<HTMLElement>(".note-body-cell--text");
  const r = (cell ?? lineEl).getBoundingClientRect();
  const h = Math.max(r.height, 8);
  return { top: r.top, height: h };
}

export function isImageGridLineBeforeDrop(clientY: number, lineEl: HTMLElement): boolean {
  const r = lineEl.getBoundingClientRect();
  return clientY <= r.top + Math.min(14, r.height * 0.1);
}

export function isWithinImageGridSideDropX(clientX: number, lineEl: HTMLElement): boolean {
  const r = lineEl.getBoundingClientRect();
  return clientX >= r.left && clientX <= r.right;
}

export function normalizeImageGridAdjacentNoop(
  from: CellPos,
  before: CellPos,
  lines: BodyLine[],
  files: NoteFile[],
): CellPos {
  const line = lines[from.line];
  if (!line || before.line !== from.line || !isImageEmbedRow(line, files)) return before;
  if (before.cell === from.cell && from.cell > 0) {
    return { line: before.line, cell: from.cell - 1 };
  }
  if (before.cell === from.cell + 1 && from.cell + 1 < line.cells.length) {
    return { line: before.line, cell: from.cell + 2 };
  }
  return before;
}

function stabilizeFlexEmbedDropCommitted(
  prev: CellPos | null,
  raw: CellPos,
  clientX: number,
  lineIndex: number,
): CellPos {
  if (!prev || prev.line !== raw.line || prev.line !== lineIndex || prev.cell === raw.cell) return raw;
  if (Math.abs(prev.cell - raw.cell) !== 1) return raw;

  const lineEl = document.querySelector<HTMLElement>(`.note-body-line[data-line="${lineIndex}"]`);
  if (!lineEl) return raw;

  const embeds = [...lineEl.children].filter(
    (el): el is HTMLElement =>
      el instanceof HTMLElement && el.classList.contains("note-body-cell--embed"),
  );

  const rectFor = (cellIdx: number) =>
    embeds.find((el) => Number(el.dataset.cell) === cellIdx)?.getBoundingClientRect();

  const lo = Math.min(prev.cell, raw.cell);
  const hi = Math.max(prev.cell, raw.cell);
  const leftEl = rectFor(lo);
  const rightEl = rectFor(hi);
  if (!leftEl || !rightEl) return raw;

  const mid = (leftEl.right + rightEl.left) / 2;
  if (Math.abs(clientX - mid) < FLEX_DROP_X_HYST_PX) return prev;
  return raw;
}

/** Пока курсор в полосе у границы «до/после» текстовой строки — держим прошлую цель, меньше дрожания. */
export function stabilizeDropBeforeCommitted(
  prev: CellPos | null,
  raw: CellPos,
  clientX: number,
  clientY: number,
  lines: BodyLine[],
  files: NoteFile[],
): CellPos {
  const hit = hitTestLine(clientX, clientY, lines, files);
  if (!hit) return raw;

  if (isTextLine(hit.line)) {
    const { top, height: h } = textLineCellMetrics(hit.lineEl);
    const boundaryY = top + h * TEXT_DROP_BOUNDARY_FRAC;
    const band = textLineDropHysteresisPx(h);
    const i = hit.lineIndex;

    if (prev && prev.cell === 0) {
      const prevLine = prev.line;
      if (prevLine === i || prevLine === i + 1) {
        if (prevLine === i) {
          if (clientY <= boundaryY + band) return prev;
          return raw;
        }
        if (prevLine === i + 1) {
          if (clientY >= boundaryY - band) return prev;
          return raw;
        }
      }
    }
    return raw;
  }

  if (!hit.isImageGrid && isEmbedLine(hit.line)) {
    return stabilizeFlexEmbedDropCommitted(prev, raw, clientX, hit.lineIndex);
  }

  return raw;
}

function unionLineBounds(els: NodeListOf<HTMLElement>): DOMRect | null {
  let top = Infinity;
  let bottom = -Infinity;
  let left = Infinity;
  let right = -Infinity;
  let hasBox = false;

  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 && r.height <= 0) continue;
    hasBox = true;
    top = Math.min(top, r.top);
    bottom = Math.max(bottom, r.bottom);
    left = Math.min(left, r.left);
    right = Math.max(right, r.right);
  }

  if (!hasBox) return null;
  return new DOMRect(left, top, right - left, bottom - top);
}

export function hitTestLine(
  clientX: number,
  clientY: number,
  lines: BodyLine[],
  files: NoteFile[],
): { line: BodyLine; lineIndex: number; lineEl: HTMLElement; isImageGrid: boolean } | null {
  const tailEl = document.querySelector<HTMLElement>('.note-body-line[data-drop-tail="1"]');
  if (tailEl) {
    const tailRect = tailEl.getBoundingClientRect();
    if (clientY >= tailRect.top && clientY <= tailRect.bottom) {
      return {
        line: { cells: [{ type: "text", content: "" }] },
        lineIndex: lines.length,
        lineEl: tailEl,
        isImageGrid: false,
      };
    }
  }

  const lineIndices = new Set<number>();
  document.querySelectorAll<HTMLElement>(".note-body-canvas [data-line]").forEach((el) => {
    const index = Number(el.dataset.line);
    if (!Number.isNaN(index)) lineIndices.add(index);
  });

  const sorted = [...lineIndices].sort((a, b) => a - b);
  let imageGridBottomEdgeHit: {
    line: BodyLine;
    lineIndex: number;
    lineEl: HTMLElement;
    isImageGrid: boolean;
  } | null = null;

  for (const li of sorted) {
    const gridEl = document.querySelector<HTMLElement>(
      `.note-body-line.note-embed-image-grid[data-line="${li}"]`,
    );
    const lineEls = document.querySelectorAll<HTMLElement>(`.note-body-canvas [data-line="${li}"]`);
    const bounds = gridEl?.getBoundingClientRect() ?? unionLineBounds(lineEls);
    if (!bounds || bounds.height <= 0) continue;

    const line = lines[li];
    if (!line) continue;
    const lineEl = gridEl ?? lineEls[0];
    if (!lineEl) continue;

    if (clientY >= bounds.top && clientY <= bounds.bottom) {
      return { line, lineIndex: li, lineEl, isImageGrid: isImageEmbedRow(line, files) };
    }

    if (
      isImageEmbedRow(line, files) &&
      clientY > bounds.bottom &&
      clientY <= bounds.bottom + IMAGE_GRID_BOTTOM_SIDE_DROP_TOLERANCE_PX &&
      isWithinImageGridSideDropX(clientX, lineEl)
    ) {
      imageGridBottomEdgeHit = { line, lineIndex: li, lineEl, isImageGrid: true };
    }
    if (clientY < bounds.top) break;
  }

  return imageGridBottomEdgeHit;
}

function imageGridMetrics(lineEl: HTMLElement) {
  const r = lineEl.getBoundingClientRect();
  const gap = EMBED_IMAGE_SLOT_GAP;
  const width = Math.max(0, r.width);
  const cellW = width > 0 ? (width - 2 * gap) / 3 : 0;
  return { left: r.left, width, cellW, gap };
}

function imageGridSlotHysteresisPx(cellW: number): number {
  return Math.max(28, Math.min(56, cellW * 0.14));
}

function rawImageGridSlot(clientX: number, lineEl: HTMLElement): number {
  const { left, width, cellW, gap } = imageGridMetrics(lineEl);
  if (width <= 0 || cellW <= 0) return 0;
  const x = clientX - left;
  if (x < 0) return 0;
  if (x >= width) return MAX_IMAGES_PER_EMBED_ROW;
  for (let i = 0; i < 3; i++) {
    const colStart = i * (cellW + gap);
    const colEnd = colStart + cellW;
    if (x < colEnd) return i;
    if (i < 2) {
      const gapEnd = colEnd + gap;
      if (x < gapEnd) {
        return x < colEnd + gap * 0.5 ? i : i + 1;
      }
    }
  }
  return MAX_IMAGES_PER_EMBED_ROW;
}

function stabilizeImageGridSlot(
  clientX: number,
  lineEl: HTMLElement,
  rawSlot: number,
  committed: number | null,
): number {
  const { left, width, cellW, gap } = imageGridMetrics(lineEl);
  if (width <= 0 || cellW <= 0 || committed == null) return rawSlot;
  const h = imageGridSlotHysteresisPx(cellW);
  const colLeft = (i: number) => left + i * (cellW + gap);
  const colRight = (i: number) => colLeft(i) + cellW;

  let slot = committed;
  if (rawSlot > slot && slot < MAX_IMAGES_PER_EMBED_ROW) {
    if (slot < 2) {
      const nextLeft = colLeft(slot + 1);
      if (clientX >= nextLeft - h) slot += 1;
    } else if (slot === 2) {
      if (clientX >= colRight(2) - h) slot += 1;
    }
  } else if (rawSlot < slot && slot > 0) {
    if (slot === MAX_IMAGES_PER_EMBED_ROW) {
      if (clientX <= colRight(2) - h) slot -= 1;
    } else if (clientX <= colLeft(slot) + h) {
      slot -= 1;
    }
  }
  return Math.max(0, Math.min(MAX_IMAGES_PER_EMBED_ROW, slot));
}

export function resolveImageGridSlot(
  clientX: number,
  lineEl: HTMLElement,
  lineIndex: number,
  line: BodyLine,
  dragSource: CellPos | null,
  committedRef: MutableRefObject<number | null>,
  slotRef: MutableRefObject<ImageDropSlot | null>,
): number {
  const raw = rawImageGridSlot(clientX, lineEl);
  const committed = slotRef.current?.line === lineIndex ? committedRef.current : null;
  const slot = stabilizeImageGridSlot(clientX, lineEl, raw, committed);
  const othersCount = Math.max(0, line.cells.length - (dragSource?.line === lineIndex ? 1 : 0));
  const normalized = Math.min(slot, othersCount);
  committedRef.current = normalized;
  return normalized;
}

export function resolveFlexEmbedDrop(
  clientX: number,
  line: BodyLine,
  lineIndex: number,
): CellPos {
  const lineEl = document.querySelector<HTMLElement>(`.note-body-line[data-line="${lineIndex}"]`);
  if (!lineEl) return { line: lineIndex, cell: 0 };

  const nodes = [...lineEl.children].filter(
    (el): el is HTMLElement => el instanceof HTMLElement && el.classList.contains("note-body-cell--embed"),
  );

  if (!nodes.length) return { line: lineIndex, cell: 0 };

  const rects = nodes.map((el) => el.getBoundingClientRect());
  if (clientX < rects[0]!.left) return { line: lineIndex, cell: Number(nodes[0]!.dataset.cell) || 0 };

  for (let i = 0; i < rects.length - 1; i++) {
    const mid = (rects[i]!.right + rects[i + 1]!.left) / 2;
    if (clientX < mid) return { line: lineIndex, cell: Number(nodes[i + 1]!.dataset.cell) || 0 };
  }

  const last = Number(nodes[nodes.length - 1]!.dataset.cell);
  return { line: lineIndex, cell: Number.isFinite(last) ? last + 1 : line.cells.length };
}
