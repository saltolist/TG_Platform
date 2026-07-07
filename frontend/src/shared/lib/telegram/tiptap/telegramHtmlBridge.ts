import type { Editor } from "@tiptap/core";
import type { Mark, Node as PMNode } from "@tiptap/pm/model";

import { sanitizeTelegramHtml } from "@/shared/lib/telegram/sanitizeTelegramHtml";

import type { PostTextContent } from "./postTextContent";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function applyMarks(text: string, marks: readonly Mark[]): string {
  let result = text;
  for (const mark of marks) {
    switch (mark.type.name) {
      case "bold":
        result = `<strong>${result}</strong>`;
        break;
      case "italic":
        result = `<em>${result}</em>`;
        break;
      case "underline":
        result = `<u>${result}</u>`;
        break;
      case "strike":
        result = `<s>${result}</s>`;
        break;
      case "code":
        result = `<code>${result}</code>`;
        break;
      case "link": {
        const href = String(mark.attrs.href ?? "").trim();
        if (href) {
          result = `<a href="${escapeHtml(href)}" rel="noopener noreferrer" target="_blank">${result}</a>`;
        }
        break;
      }
      case "spoiler":
        result = `<span class="tg-spoiler">${result}</span>`;
        break;
      default:
        break;
    }
  }

  return result;
}

function serializeInlineNode(node: PMNode): string {
  if (node.type.name === "telegramCustomEmoji") {
    const documentId = String(node.attrs.documentId ?? "");
    const alt = escapeHtml(String(node.attrs.alt ?? "⭐"));
    return `<tg-emoji emoji-id="${escapeHtml(documentId)}">${alt}</tg-emoji>`;
  }
  if (node.isText) {
    return applyMarks(escapeHtml(node.text ?? ""), node.marks);
  }
  if (node.type.name === "hardBreak") {
    return "<br>";
  }
  return "";
}

function serializeParagraph(node: PMNode): string {
  let html = "";
  node.forEach((child) => {
    html += serializeInlineNode(child);
  });
  return html;
}

export function docToTelegramHtml(doc: PMNode): string {
  const parts: string[] = [];
  doc.forEach((child) => {
    if (child.type.name === "paragraph") {
      parts.push(serializeParagraph(child));
    }
  });
  return parts.join("<br>");
}

function extractInlinePlainText(node: PMNode): string {
  if (node.type.name === "telegramCustomEmoji") {
    return String(node.attrs.alt ?? "⭐");
  }
  if (node.isText) {
    return node.text ?? "";
  }
  if (node.type.name === "hardBreak") {
    return "\n";
  }
  return "";
}

function extractPlainTextFromParagraph(node: PMNode): string {
  let text = "";
  node.forEach((child) => {
    text += extractInlinePlainText(child);
  });
  return text;
}

export function extractPlainTextFromDoc(doc: PMNode): string {
  const parts: string[] = [];
  doc.forEach((child, _offset, index) => {
    if (child.type.name === "paragraph") {
      if (index > 0) parts.push("\n");
      parts.push(extractPlainTextFromParagraph(child));
    }
  });
  return parts.join("").replace(/\n+$/, "");
}

function plainTextToEditorHtml(text: string): string {
  if (!text) return "<p></p>";
  const lines = text.split("\n");
  return lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("");
}

function telegramHtmlToEditorHtml(html: string): string {
  const sanitized = sanitizeTelegramHtml(html);
  if (!sanitized) return "<p></p>";
  const parts = sanitized.split(/<br\s*\/?>/i);
  return parts.map((part) => `<p>${part}</p>`).join("");
}

export function postContentToEditorHtml(content: PostTextContent): string {
  const html = content.textHtml?.trim();
  if (html) {
    return telegramHtmlToEditorHtml(html);
  }
  return plainTextToEditorHtml(content.text ?? "");
}

export function editorToPostContent(editor: Editor): PostTextContent {
  const text = extractPlainTextFromDoc(editor.state.doc).trim();
  const rawHtml = docToTelegramHtml(editor.state.doc).trim();

  if (!text && !rawHtml) {
    return { text: "" };
  }

  const sanitized = sanitizeTelegramHtml(rawHtml);
  if (!sanitized) {
    return { text };
  }

  const plainFromHtml = extractPlainTextFromSanitizedHtml(sanitized).trim();
  if (!plainFromHtml || plainFromHtml !== text) {
    return { text };
  }

  const escaped = escapeHtml(text).replace(/\n/g, "<br>");
  if (sanitized === escaped) {
    return { text };
  }

  return { text, textHtml: sanitized };
}

function extractPlainTextFromSanitizedHtml(html: string): string {
  if (typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  const container = document.createElement("div");
  container.innerHTML = doc.body.innerHTML;

  function walk(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent ?? "";
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const el = node as HTMLElement;
    const tag = el.tagName.toLowerCase();
    if (tag === "br") return "\n";
    if (tag === "tg-emoji") return el.textContent ?? "";
    let text = "";
    el.childNodes.forEach((child) => {
      text += walk(child);
    });
    return text;
  }

  let text = "";
  container.childNodes.forEach((child) => {
    text += walk(child);
  });
  return text.replace(/\n+$/, "");
}
