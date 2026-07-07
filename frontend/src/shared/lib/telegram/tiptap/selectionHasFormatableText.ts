import type { Editor } from "@tiptap/core";
import { TextSelection } from "@tiptap/pm/state";

/** True when the editor selection spans at least one real text node. */
export function selectionHasFormatableText(editor: Editor): boolean {
  const { selection } = editor.state;
  if (!(selection instanceof TextSelection) || selection.empty) {
    return false;
  }

  const { from, to } = selection;
  let hasFormatableText = false;

  editor.state.doc.nodesBetween(from, to, (node) => {
    if (hasFormatableText) return false;
    if (node.isText && node.text) {
      hasFormatableText = true;
      return false;
    }
    return;
  });

  return hasFormatableText;
}

export function isFormatBubbleSelection(editor: Editor): boolean {
  return selectionHasFormatableText(editor);
}
