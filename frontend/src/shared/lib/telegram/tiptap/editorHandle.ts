import type { Editor } from "@tiptap/core";

import type { PostTextContent } from "./postTextContent";
import { editorToPostContent } from "./telegramHtmlBridge";

export type TelegramPostEditorHandle = {
  insertUnicodeEmoji: (char: string) => void;
  insertCustomEmoji: (documentId: string, alt?: string) => void;
  serialize: () => PostTextContent;
  focus: () => void;
  getEditor: () => Editor | null;
};

export function createEditorHandle(editor: Editor | null): TelegramPostEditorHandle | null {
  if (!editor) return null;
  return {
    insertUnicodeEmoji: (char) => {
      if (!char) return;
      editor.chain().focus().insertContent(char).run();
    },
    insertCustomEmoji: (documentId, alt = "⭐") => {
      if (!documentId) return;
      editor.chain().focus().insertTelegramEmoji({ documentId, alt }).run();
    },
    serialize: () => editorToPostContent(editor),
    focus: () => {
      editor.chain().focus().run();
    },
    getEditor: () => editor,
  };
}
