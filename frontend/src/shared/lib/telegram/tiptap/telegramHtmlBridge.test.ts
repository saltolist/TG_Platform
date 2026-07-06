/** @vitest-environment jsdom */

import { Editor } from "@tiptap/core";
import { describe, expect, it } from "vitest";

import { getTelegramPostExtensions } from "./telegramExtensions";
import {
  docToTelegramHtml,
  editorToPostContent,
  postContentToEditorHtml,
} from "./telegramHtmlBridge";

function createTestEditor(content: string) {
  return new Editor({
    extensions: getTelegramPostExtensions(),
    content,
  });
}

describe("telegramHtmlBridge", () => {
  it("serializes bold formatting into textHtml", () => {
    const editor = createTestEditor("<p><strong>bold</strong> text</p>");
    expect(editorToPostContent(editor)).toEqual({
      text: "bold text",
      textHtml: "<strong>bold</strong> text",
    });
    editor.destroy();
  });

  it("returns plain text when formatting is absent", () => {
    const editor = createTestEditor("<p>plain text</p>");
    expect(editorToPostContent(editor)).toEqual({ text: "plain text" });
    editor.destroy();
  });

  it("preserves line breaks via br tags", () => {
    const editor = createTestEditor("<p>first</p><p>second</p>");
    expect(docToTelegramHtml(editor.state.doc)).toBe("first<br>second");
    expect(editorToPostContent(editor).text).toBe("first\nsecond");
    editor.destroy();
  });

  it("loads existing textHtml into the editor", () => {
    const html = postContentToEditorHtml({
      text: "hidden",
      textHtml: '<span class="tg-spoiler">hidden</span>',
    });
    const editor = createTestEditor(html);
    expect(editor.getHTML()).toContain("tg-spoiler");
    editor.destroy();
  });

  it("serializes custom emoji into tg-emoji", () => {
    const editor = createTestEditor(
      postContentToEditorHtml({
        text: "⭐",
        textHtml: '<tg-emoji emoji-id="42">⭐</tg-emoji>',
      }),
    );
    expect(editorToPostContent(editor)).toEqual({
      text: "⭐",
      textHtml: '<tg-emoji emoji-id="42">⭐</tg-emoji>',
    });
    editor.destroy();
  });

  it("inserts custom emoji with alt in plain text", () => {
    const editor = createTestEditor("<p>hi</p>");
    editor.commands.setTextSelection(editor.state.doc.content.size);
    editor.commands.insertTelegramEmoji({ documentId: "99", alt: "🎉" });
    expect(editorToPostContent(editor)).toEqual({
      text: "hi🎉",
      textHtml: 'hi<tg-emoji emoji-id="99">🎉</tg-emoji>',
    });
    editor.destroy();
  });

  it("inserts unicode emoji at cursor", () => {
    const editor = createTestEditor("<p>hi</p>");
    editor.commands.focus("end");
    editor.commands.insertContent("😀");
    expect(editorToPostContent(editor).text).toBe("hi😀");
    editor.destroy();
  });
});
