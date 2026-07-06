import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, TextSelection } from "@tiptap/pm/state";

function docSelectionHasFormatableText(doc: ProseMirrorNode, from: number, to: number): boolean {
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

/** Collapse selections that only cover custom emoji atoms (browser/PM quirk near inline atoms). */
export const CollapseEmojiOnlySelection = Extension.create({
  name: "collapseEmojiOnlySelection",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        appendTransaction: (_transactions, _oldState, newState) => {
          const { selection, doc } = newState;
          if (!(selection instanceof TextSelection) || selection.empty) return null;
          if (docSelectionHasFormatableText(doc, selection.from, selection.to)) return null;

          return newState.tr.setSelection(TextSelection.create(doc, selection.head));
        },
      }),
    ];
  },
});
