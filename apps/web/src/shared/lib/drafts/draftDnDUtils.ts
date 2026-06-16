import type { Post } from "@/shared/types";

export type DraftDragItem = { id: string; r: DOMRect };

export type DraftDisplayItem = { kind: "card"; post: Post } | { kind: "gap"; key: string };

export function collectDraftDragItems(
  drafts: Post[],
  cardRefs: Map<string, HTMLDivElement>,
): DraftDragItem[] {
  return drafts
    .map((d) => {
      const el = cardRefs.get(d.id);
      const r = el?.getBoundingClientRect();
      return r && r.height > 0 ? { id: d.id, r } : null;
    })
    .filter((x): x is DraftDragItem => x != null);
}

export function appendZoneBottom(items: DraftDragItem[], container: HTMLElement | null): number {
  const last = items[items.length - 1]?.r.bottom ?? 0;
  const containerBottom = container?.getBoundingClientRect().bottom ?? last;
  const feed = document.getElementById("feed-scroll");
  const feedBottom = feed?.getBoundingClientRect().bottom ?? containerBottom;
  return Math.max(last, containerBottom, feedBottom - 8);
}

/**
 * Границы слотов 0..k (k = visibleCards + 1).
 * Слот i — вставка перед items[i]; слот k — в конец.
 */
export function slotBoundariesForVisible(items: DraftDragItem[], appendBottom: number): number[] {
  const k = items.length;
  if (k === 0) return [appendBottom];
  if (k === 1) {
    const r = items[0]!.r;
    return [r.top, Math.max(r.bottom, appendBottom)];
  }

  const boundaries: number[] = [items[0]!.r.top];
  for (let i = 1; i < k; i++) {
    boundaries.push((items[i - 1]!.r.bottom + items[i]!.r.top) / 2);
  }
  const last = items[k - 1]!.r;
  boundaries.push(Math.max(last.bottom, appendBottom));
  return boundaries;
}

export function yToRawSlot(y: number, boundaries: number[], slotCount: number): number {
  for (let slot = 0; slot < slotCount; slot++) {
    if (y < boundaries[slot]!) return slot;
  }
  return slotCount;
}

export function stabilizeSlot(
  y: number,
  rawSlot: number,
  boundaries: number[],
  slotCount: number,
  committed: number | null,
): number {
  const HY = 12;
  if (slotCount <= 1) return rawSlot;

  let slot = committed ?? rawSlot;
  if (rawSlot > slot) {
    while (slot < rawSlot) {
      const threshold = boundaries[slot];
      if (threshold != null && y >= threshold + HY) slot++;
      else break;
    }
  } else if (rawSlot < slot) {
    while (slot > rawSlot) {
      const threshold = boundaries[slot - 1];
      if (threshold != null && y <= threshold - HY) slot--;
      else break;
    }
  }
  return slot;
}

export function buildDraftDisplayList(
  drafts: Post[],
  dragId: string | null,
  beforeId: string | null,
): DraftDisplayItem[] {
  if (dragId == null) {
    return drafts.map((post) => ({ kind: "card", post }));
  }

  const withoutDrag = drafts.filter((p) => p.id !== dragId);
  let insertAt = withoutDrag.length;

  if (beforeId != null) {
    const idx = withoutDrag.findIndex((p) => p.id === beforeId);
    if (idx >= 0) {
      insertAt = idx;
    } else {
      insertAt = drafts.findIndex((p) => p.id === dragId);
      if (insertAt < 0) insertAt = withoutDrag.length;
    }
  }

  const items: DraftDisplayItem[] = [];
  withoutDrag.forEach((post, i) => {
    if (i === insertAt) items.push({ kind: "gap", key: `gap-${i}` });
    items.push({ kind: "card", post });
  });
  if (insertAt >= withoutDrag.length) {
    items.push({ kind: "gap", key: "gap-end" });
  }
  return items;
}
