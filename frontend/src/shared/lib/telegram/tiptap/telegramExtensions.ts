import Bold from "@tiptap/extension-bold";
import Code from "@tiptap/extension-code";
import Document from "@tiptap/extension-document";
import HardBreak from "@tiptap/extension-hard-break";
import History from "@tiptap/extension-history";
import Italic from "@tiptap/extension-italic";
import Link from "@tiptap/extension-link";
import Paragraph from "@tiptap/extension-paragraph";
import Placeholder from "@tiptap/extension-placeholder";
import Strike from "@tiptap/extension-strike";
import Text from "@tiptap/extension-text";
import Underline from "@tiptap/extension-underline";

import { CollapseEmojiOnlySelection } from "./extensions/collapseEmojiOnlySelection";
import { Spoiler } from "./extensions/spoiler";
import { TelegramEmoji } from "./extensions/telegramEmoji";

export type TelegramPostExtensionOptions = {
  placeholder?: string;
};

export function getTelegramPostExtensions(options: TelegramPostExtensionOptions = {}) {
  const { placeholder } = options;

  return [
    Document,
    Paragraph,
    Text,
    HardBreak,
    Bold,
    Italic,
    Underline,
    Strike,
    Code,
    Link.configure({
      openOnClick: false,
      autolink: false,
      linkOnPaste: false,
    }),
    Spoiler,
    TelegramEmoji,
    CollapseEmojiOnlySelection,
    History,
    Placeholder.configure({
      placeholder: placeholder ?? "",
      emptyEditorClass: "rich-text-input--empty",
    }),
  ];
}
