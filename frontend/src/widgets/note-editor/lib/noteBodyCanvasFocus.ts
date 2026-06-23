/** Не перехватывать клик по embed-ссылкам и картинкам в режиме просмотра. */
export function shouldHandleBodyCanvasPointerDown(
  target: EventTarget | null,
  canvas: HTMLElement,
): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (!canvas.contains(target)) return false;
  if (target.closest("a, button, img.note-inline-image, .note-embed-chip")) {
    return false;
  }
  return true;
}

/** Фокус редактора тела заметки по координатам клика внутри canvas. */
export function focusNoteBodyAtPoint(canvas: HTMLElement, _clientX: number, _clientY: number): boolean {
  const editor = canvas.querySelector<HTMLElement>(".ProseMirror");
  if (!editor) return false;
  editor.focus();
  return true;
}

/** Индекс каретки по Y/X внутри textarea с известной высотой строки и измерителем ширины префикса. */
export function caretIndexFromTextareaGeometry(
  value: string,
  relativeY: number,
  relativeX: number,
  lineHeight: number,
  measurePrefixWidth: (line: string, charIndex: number) => number,
): number {
  if (!value) return 0;

  const lines = value.split("\n");
  const safeLineHeight = lineHeight > 0 ? lineHeight : 1;
  let lineIdx = Math.floor(relativeY / safeLineHeight);
  lineIdx = Math.max(0, Math.min(lineIdx, lines.length - 1));

  const lineText = lines[lineIdx] ?? "";
  let charInLine = 0;
  if (lineText.length > 0 && relativeX > 0) {
    let lo = 0;
    let hi = lineText.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (measurePrefixWidth(lineText, mid) <= relativeX) lo = mid;
      else hi = mid - 1;
    }
    charInLine = lo;
  }

  let index = 0;
  for (let i = 0; i < lineIdx; i++) {
    index += lines[i]!.length + 1;
  }
  index += charInLine;
  return Math.max(0, Math.min(index, value.length));
}
