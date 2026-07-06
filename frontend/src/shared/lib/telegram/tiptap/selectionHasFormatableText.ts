import type { Editor } from "@tiptap/core";
import { TextSelection } from "@tiptap/pm/state";

/** True when the editor selection spans at least one real text node (not only custom emoji atoms). */
export function selectionHasFormatableText(editor: Editor): boolean {
  const { selection, doc } = editor.state;
  if (!(selection instanceof TextSelection) || selection.empty) {
    return false;
  }

  const { from, to } = selection;
  let hasFormatableText = false;

  doc.nodesBetween(from, to, (node) => {
    if (hasFormatableText) return false;
    if (node.type.name === "telegramEmoji") return;
    if (node.isText && node.text) {
      hasFormatableText = true;
      return false;
    }
    return;
  });

  return hasFormatableText;
}
