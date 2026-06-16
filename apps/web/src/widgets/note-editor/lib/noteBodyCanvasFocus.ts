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

function readLineHeight(style: CSSStyleDeclaration, fontSize: number): number {
  if (style.lineHeight === "normal") return fontSize * 1.2;
  const parsed = parseFloat(style.lineHeight);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fontSize * 1.2;
}

function measureTextPrefixWidth(
  line: string,
  charIndex: number,
  style: CSSStyleDeclaration,
): number {
  if (charIndex <= 0) return 0;
  const probe = document.createElement("span");
  probe.textContent = line.slice(0, charIndex);
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  probe.style.whiteSpace = "pre-wrap";
  probe.style.font = style.font;
  probe.style.letterSpacing = style.letterSpacing;
  probe.style.wordBreak = style.wordBreak;
  document.body.appendChild(probe);
  const width = probe.getBoundingClientRect().width;
  probe.remove();
  return width;
}

function placeCaretInTextarea(ta: HTMLTextAreaElement, clientX: number, clientY: number) {
  ta.focus();
  const rect = ta.getBoundingClientRect();
  const style = window.getComputedStyle(ta);
  const paddingTop = parseFloat(style.paddingTop) || 0;
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  const fontSize = parseFloat(style.fontSize) || 15;
  const lineHeight = readLineHeight(style, fontSize);
  const relativeY = clientY - rect.top - paddingTop + ta.scrollTop;
  const relativeX = Math.max(
    0,
    Math.min(clientX - rect.left - paddingLeft, ta.clientWidth - paddingLeft - paddingRight),
  );
  const index = caretIndexFromTextareaGeometry(
    ta.value,
    relativeY,
    relativeX,
    lineHeight,
    (line, charIndex) => measureTextPrefixWidth(line, charIndex, style),
  );
  ta.setSelectionRange(index, index);
}

/** Не перехватывать клик по embed-ссылкам и картинкам в режиме просмотра. */
export function shouldHandleBodyCanvasPointerDown(
  target: EventTarget | null,
  canvas: HTMLElement,
): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (!canvas.contains(target)) return false;
  if (target.closest(".note-body-line-edit")) return false;
  if (target.closest("a, button, img.note-inline-image, .note-embed-chip, .note-body-cell--embed")) {
    return false;
  }
  return true;
}

/** Сразу обновить cursor на canvas при смене view/edit (без движения мыши). */
export function refreshBodyCanvasCursor(canvas: HTMLElement, isView: boolean): void {
  canvas.style.cursor = isView ? "default" : "text";
}

/** Фокус строки тела заметки по координатам клика внутри canvas. */
export function focusNoteBodyAtPoint(canvas: HTMLElement, clientX: number, clientY: number): boolean {
  const ta = canvas.querySelector<HTMLTextAreaElement>(".note-body-document-edit--mirror");
  if (!ta) return false;
  placeCaretInTextarea(ta, clientX, clientY);
  return true;
}
