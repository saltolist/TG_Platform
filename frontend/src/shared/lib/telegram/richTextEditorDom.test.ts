/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import {
  applyRichTextFormat,
  extractPlainTextFromEditor,
  serializeRichTextEditor,
  setRichTextContent,
} from "./richTextEditorDom";

describe("richTextEditorDom", () => {
  function makeEditor(html = "") {
    const root = document.createElement("div");
    root.innerHTML = html;
    document.body.appendChild(root);
    return root;
  }

  it("serializes bold formatting into textHtml", () => {
    const root = makeEditor("<strong>bold</strong> text");
    expect(serializeRichTextEditor(root)).toEqual({
      text: "bold text",
      textHtml: "<strong>bold</strong> text",
    });
    root.remove();
  });

  it("returns plain text when formatting is absent", () => {
    const root = makeEditor("plain text");
    expect(serializeRichTextEditor(root)).toEqual({ text: "plain text" });
    root.remove();
  });

  it("preserves line breaks via br tags", () => {
    const root = makeEditor("first<br>second");
    expect(extractPlainTextFromEditor(root)).toBe("first\nsecond");
    root.remove();
  });

  it("loads existing textHtml into the editor", () => {
    const root = makeEditor();
    setRichTextContent(root, {
      text: "hidden",
      textHtml: '<span class="tg-spoiler">hidden</span>',
    });
    expect(root.querySelector(".tg-spoiler")?.textContent).toBe("hidden");
    root.remove();
  });

  it("wraps selection with spoiler markup", () => {
    const root = makeEditor("secret word");
    root.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.setStart(root.firstChild!, 0);
    range.setEnd(root.firstChild!, 6);
    selection?.removeAllRanges();
    selection?.addRange(range);

    applyRichTextFormat("spoiler");

    expect(root.innerHTML).toContain('class="tg-spoiler"');
    expect(serializeRichTextEditor(root).textHtml).toContain("tg-spoiler");
    root.remove();
  });
});
