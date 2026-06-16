import type { EntityOverlay } from "@/shared/lib/overlay/overlayTypes";

export function mergeEntityList<T extends { id: string }>(
  base: T[],
  overlay: EntityOverlay<T>,
  order?: string[],
): T[] {
  const removed = new Set(overlay.removedIds);
  const map = new Map<string, T>();

  for (const item of base) {
    if (!removed.has(item.id)) {
      map.set(item.id, item);
    }
  }
  for (const [id, item] of Object.entries(overlay.upserts)) {
    if (!removed.has(id)) {
      map.set(id, item);
    }
  }

  if (order?.length) {
    const result: T[] = [];
    const seen = new Set<string>();
    for (const id of order) {
      const item = map.get(id);
      if (item) {
        result.push(item);
        seen.add(id);
      }
    }
    for (const [id, item] of map) {
      if (!seen.has(id)) result.push(item);
    }
    return result;
  }

  const baseIds = new Set(base.map((item) => item.id));
  const ordered: T[] = [];
  const used = new Set<string>();

  for (const item of base) {
    const merged = map.get(item.id);
    if (merged && !removed.has(item.id)) {
      ordered.push(merged);
      used.add(item.id);
    }
  }
  for (const [id, item] of Object.entries(overlay.upserts)) {
    if (!used.has(id) && !removed.has(id)) {
      ordered.unshift(item);
    }
  }
  return ordered;
}
