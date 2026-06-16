const DEFAULT_CONTENT = "width=device-width, initial-scale=1";
const LOCKED_CONTENT = "width=device-width, initial-scale=1, maximum-scale=1";

let lockCount = 0;
let savedContent: string | null = null;

function viewportMeta(): HTMLMetaElement | null {
  return document.querySelector('meta[name="viewport"]');
}

/** Блокирует pinch/focus-zoom (iOS при font-size < 16px). Счётчик для вложенных focus. */
export function lockViewportZoom(): void {
  const meta = viewportMeta();
  if (!meta) return;
  if (lockCount === 0) {
    savedContent = meta.getAttribute("content");
    meta.setAttribute("content", LOCKED_CONTENT);
  }
  lockCount += 1;
}

export function unlockViewportZoom(): void {
  if (lockCount === 0) return;
  lockCount -= 1;
  if (lockCount > 0) return;
  const meta = viewportMeta();
  if (!meta) return;
  meta.setAttribute("content", savedContent ?? DEFAULT_CONTENT);
  savedContent = null;
}
