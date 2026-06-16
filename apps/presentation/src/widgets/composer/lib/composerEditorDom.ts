import { serializeChip } from "@/widgets/composer/lib/composerChipUtils";
import type { MentionState } from "@/widgets/composer/model/editor/types";
import type { ComposerAttachment } from "@/shared/types";

const INVISIBLE_CHARS = /[\u200b\u00a0]/g;
const WHITESPACE_ONLY = /[\u200b\u00a0\s]/g;

export function isEditorEmpty(el: HTMLElement): boolean {
  if (el.querySelector(".inline-chip")) return false;
  const text = (el.textContent || "").replace(INVISIBLE_CHARS, "").replace(/\s/g, "").trim();
  return text.length === 0;
}

export function pruneOrphanComposerSpaces(editor: HTMLElement): void {
  Array.from(editor.childNodes).forEach((node) => {
    if (node.nodeType !== Node.TEXT_NODE) return;
    const raw = node.textContent || "";
    if (raw.replace(WHITESPACE_ONLY, "").length === 0) node.remove();
  });
}

export function placeCaretAtStart(editor: HTMLElement): void {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.setStart(editor, 0);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

export function placeCaretAfter(node: Node): void {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.setStartAfter(node);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

export function detectMentionFromSelection(editor: HTMLElement): MentionState {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!editor.contains(range.startContainer)) return null;
  const node = range.startContainer;
  if (node.nodeType !== Node.TEXT_NODE) return null;
  const text = node.textContent || "";
  const caret = range.startOffset;
  let atIdx = -1;
  for (let i = caret - 1; i >= 0; i -= 1) {
    const ch = text[i];
    if (ch === "@") {
      atIdx = i;
      break;
    }
    if (ch === " " || ch === "\n" || ch === "\t" || ch === ";") return null;
  }
  if (atIdx < 0) return null;
  const before = atIdx === 0 ? "" : text[atIdx - 1];
  if (before && !/[\s\n]/.test(before)) return null;
  const query = text.slice(atIdx + 1, caret);
  if (query.length > 60) return null;
  return { textNode: node as Text, atOffset: atIdx, caretOffset: caret, query };
}

export function collectAttachmentsFromDom(
  editor: HTMLElement,
  attachments: ComposerAttachment[],
): ComposerAttachment[] {
  const ids = new Set<string>();
  editor.querySelectorAll<HTMLElement>(".inline-chip").forEach((el) => {
    const id = el.getAttribute("data-attach-id");
    if (id) ids.add(id);
  });
  return attachments.filter((a) => ids.has(a.id));
}

export function serializeEditorContent(
  editor: HTMLElement,
  attachments: ComposerAttachment[],
): string {
  const segments: string[] = [];
  const present = new Map<string, ComposerAttachment>(attachments.map((a) => [a.id, a]));

  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      segments.push(node.textContent || "");
      return;
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as HTMLElement;
      if (el.classList.contains("inline-chip")) {
        const id = el.getAttribute("data-attach-id");
        const att = id ? present.get(id) : null;
        if (att) segments.push(serializeChip(att));
        return;
      }
      if (el.tagName === "BR") {
        segments.push("\n");
        return;
      }
      if (el.tagName === "DIV" || el.tagName === "P") {
        segments.push("\n");
      }
      el.childNodes.forEach((c) => walk(c));
    }
  };

  editor.childNodes.forEach((c) => walk(c));
  return segments.join("").replace(/\n{3,}/g, "\n\n").trim();
}
