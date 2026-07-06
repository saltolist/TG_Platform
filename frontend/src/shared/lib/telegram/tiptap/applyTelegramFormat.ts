import type { Editor } from "@tiptap/core";

import type { RichTextFormat } from "@/shared/lib/telegram/richTextFormat";

type FormatCommands = {
  toggleBold: () => boolean;
  toggleItalic: () => boolean;
  toggleUnderline: () => boolean;
  toggleStrike: () => boolean;
  toggleCode: () => boolean;
  toggleMark: (name: string) => boolean;
  extendMarkRange: (name: string) => boolean;
  setLink: (attrs: { href: string }) => boolean;
};

export function applyTelegramFormat(editor: Editor, format: RichTextFormat, url?: string): void {
  const commands = editor.commands as Editor["commands"] & FormatCommands;
  editor.commands.focus();

  switch (format) {
    case "bold":
      commands.toggleBold();
      break;
    case "italic":
      commands.toggleItalic();
      break;
    case "underline":
      commands.toggleUnderline();
      break;
    case "strike":
      commands.toggleStrike();
      break;
    case "code":
      commands.toggleCode();
      break;
    case "spoiler":
      commands.toggleMark("spoiler");
      break;
    case "link": {
      const href = (url ?? window.prompt("Ссылка", "https://") ?? "").trim();
      if (!href) return;
      commands.extendMarkRange("link");
      commands.setLink({ href });
      break;
    }
    default:
      break;
  }
}
