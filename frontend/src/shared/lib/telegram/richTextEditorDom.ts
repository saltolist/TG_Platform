import { sanitizeTelegramHtml } from "@/shared/lib/telegram/sanitizeTelegramHtml";

export type PostTextContent = {
  text: string;
  textHtml?: string;
};

export type RichTextFormat =
  | "bold"
  | "italic"
  | "underline"
  | "strike"
  | "spoiler"
  | "code"
  | "link";

const TAG_ALIASES: Record<string, string> = {
  b: "strong",
  i: "em",
  strike: "s",
};

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function normalizeEditorElement(element: HTMLElement): void {
  const tag = element.tagName.toLowerCase();
  const replacement = TAG_ALIASES[tag];
  if (replacement) {
    const next = document.createElement(replacement);
    while (element.firstChild) {
      next.appendChild(element.firstChild);
    }
    element.replaceWith(next);
    normalizeEditorTree(next);
    return;
  }

  if (tag === "font" || tag === "span") {
    const className = element.getAttribute("class") ?? "";
    const isSpoiler = className.split(/\s+/).includes("tg-spoiler");
    if (!isSpoiler) {
      const parent = element.parentNode;
      if (parent) {
        while (element.firstChild) {
          parent.insertBefore(element.firstChild, element);
        }
        parent.removeChild(element);
      }
      return;
    }
  }

  normalizeEditorTree(element);
}

function normalizeEditorTree(root: ParentNode): void {
  const children = Array.from(root.childNodes);
  for (const child of children) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      normalizeEditorElement(child as HTMLElement);
    }
  }
}

export function normalizeEditorHtml(html: string): string {
  if (typeof DOMParser === "undefined") return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  normalizeEditorTree(doc.body);
  const container = document.createElement("div");
  doc.body.childNodes.forEach((child) => {
    container.appendChild(child.cloneNode(true));
  });
  return container.innerHTML;
}

function nodeToPlainText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? "";
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node as HTMLElement;
  const tag = el.tagName.toLowerCase();
  if (tag === "br") return "\n";
  let text = "";
  el.childNodes.forEach((child) => {
    text += nodeToPlainText(child);
  });
  if (tag === "div" || tag === "p") {
    return `${text}\n`;
  }
  return text;
}

export function extractPlainTextFromEditor(root: HTMLElement): string {
  let text = "";
  root.childNodes.forEach((child) => {
    text += nodeToPlainText(child);
  });
  return text.replace(/\n+$/, "");
}

function plainTextToEditorHtml(text: string): string {
  if (!text) return "";
  return text
    .split("\n")
    .map((line) => (line ? escapeHtml(line) : ""))
    .join("<br>");
}

export function serializeRichTextEditor(root: HTMLElement): PostTextContent {
  const text = extractPlainTextFromEditor(root).trim();
  const rawHtml = normalizeEditorHtml(root.innerHTML).trim();
  if (!text && !rawHtml) return { text: "" };

  const sanitized = sanitizeTelegramHtml(rawHtml);
  if (!sanitized) {
    return { text };
  }

  const plainFromHtml = extractPlainTextFromEditor(
    Object.assign(document.createElement("div"), { innerHTML: sanitized }),
  ).trim();

  if (!plainFromHtml || plainFromHtml !== text) {
    return { text };
  }

  const escaped = escapeHtml(text).replace(/\n/g, "<br>");
  if (sanitized === escaped) {
    return { text };
  }

  return { text, textHtml: sanitized };
}

export function setRichTextContent(root: HTMLElement, value: PostTextContent): void {
  const html = value.textHtml?.trim();
  if (html) {
    root.innerHTML = sanitizeTelegramHtml(html);
    return;
  }

  const text = value.text ?? "";
  if (!text) {
    root.innerHTML = "";
    return;
  }

  root.innerHTML = sanitizeTelegramHtml(plainTextToEditorHtml(text));
}

function wrapSelectionWithElement(tagName: string, attrs: Record<string, string> = {}): void {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return;
  const range = selection.getRangeAt(0);
  if (range.collapsed) return;

  const el = document.createElement(tagName);
  for (const [key, value] of Object.entries(attrs)) {
    el.setAttribute(key, value);
  }

  try {
    range.surroundContents(el);
  } catch {
    const fragment = range.extractContents();
    el.appendChild(fragment);
    range.insertNode(el);
  }

  selection.removeAllRanges();
  const nextRange = document.createRange();
  nextRange.selectNodeContents(el);
  nextRange.collapse(false);
  selection.addRange(nextRange);
}

export function applyRichTextFormat(format: RichTextFormat, url?: string): void {
  if (typeof document === "undefined") return;

  switch (format) {
    case "bold":
      document.execCommand("bold");
      break;
    case "italic":
      document.execCommand("italic");
      break;
    case "underline":
      document.execCommand("underline");
      break;
    case "strike":
      document.execCommand("strikeThrough");
      break;
    case "code":
      wrapSelectionWithElement("code");
      break;
    case "spoiler":
      wrapSelectionWithElement("span", { class: "tg-spoiler" });
      break;
    case "link": {
      const href = (url ?? window.prompt("Ссылка", "https://") ?? "").trim();
      if (!href) return;
      document.execCommand("createLink", false, href);
      break;
    }
    default:
      break;
  }
}

export function autoResizeRichTextEditor(root: HTMLElement, minHeight = 16): void {
  root.style.height = "auto";
  root.style.height = `${Math.max(minHeight, root.scrollHeight)}px`;
}
