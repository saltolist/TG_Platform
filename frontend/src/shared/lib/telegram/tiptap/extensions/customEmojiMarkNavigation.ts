import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";

const TELEGRAM_CUSTOM_EMOJI = "telegramCustomEmoji";

function isNavigationKey(key: string): boolean {
  return (
    key === "ArrowLeft" ||
    key === "ArrowRight" ||
    key === "ArrowUp" ||
    key === "ArrowDown" ||
    key === "Home" ||
    key === "End"
  );
}

function textNodeHasCustomEmojiMark(node: ProseMirrorNode | null | undefined): boolean {
  return Boolean(node?.isText && node.marks.some((mark) => mark.type.name === TELEGRAM_CUSTOM_EMOJI));
}

function hasCustomEmojiMarkAt(doc: ProseMirrorNode, pos: number): boolean {
  if (pos < 0 || pos > doc.content.size) return false;
  return doc.resolve(pos).marks().some((mark) => mark.type.name === TELEGRAM_CUSTOM_EMOJI);
}

function isImmediatelyBeforeCustomEmoji(doc: ProseMirrorNode, pos: number): boolean {
  const $pos = doc.resolve(pos);
  if (textNodeHasCustomEmojiMark($pos.nodeAfter)) return true;
  return hasCustomEmojiMarkAt(doc, pos);
}

function isImmediatelyAfterCustomEmoji(doc: ProseMirrorNode, pos: number): boolean {
  if (pos <= 0) return false;
  const $pos = doc.resolve(pos);
  if (textNodeHasCustomEmojiMark($pos.nodeBefore)) return true;
  return hasCustomEmojiMarkAt(doc, pos - 1);
}

function moveSelection(view: EditorView, pos: number) {
  view.dispatch(
    view.state.tr.setSelection(TextSelection.create(view.state.doc, pos)).scrollIntoView(),
  );
}

const customEmojiMarkNavigationKey = new PluginKey("customEmojiMarkNavigation");

/** Skip custom emoji marks on arrow keys; delete them atomically on Backspace/Delete. */
export const CustomEmojiMarkNavigation = Extension.create({
  name: "customEmojiMarkNavigation",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: customEmojiMarkNavigationKey,
        props: {
          handleKeyDown(view, event) {
            if (event.shiftKey) return false;

            const { selection, doc } = view.state;

            if (event.key === "Backspace" && selection instanceof TextSelection && selection.empty) {
              const nodeBefore = selection.$from.nodeBefore;
              if (textNodeHasCustomEmojiMark(nodeBefore)) {
                view.dispatch(
                  view.state.tr
                    .delete(selection.from - nodeBefore!.nodeSize, selection.from)
                    .scrollIntoView(),
                );
                event.preventDefault();
                return true;
              }
            }

            if (event.key === "Delete" && selection instanceof TextSelection && selection.empty) {
              const nodeAfter = selection.$from.nodeAfter;
              if (textNodeHasCustomEmojiMark(nodeAfter)) {
                view.dispatch(
                  view.state.tr.delete(selection.from, selection.from + nodeAfter!.nodeSize).scrollIntoView(),
                );
                event.preventDefault();
                return true;
              }
            }

            if (!isNavigationKey(event.key)) return false;
            if (!(selection instanceof TextSelection) || !selection.empty) return false;

            if (event.key === "ArrowRight") {
              if (isImmediatelyBeforeCustomEmoji(doc, selection.from)) {
                const nodeAfter = selection.$from.nodeAfter;
                const nextPos = textNodeHasCustomEmojiMark(nodeAfter)
                  ? selection.from + nodeAfter!.nodeSize
                  : selection.from + 1;
                moveSelection(view, nextPos);
                event.preventDefault();
                return true;
              }

              if (isImmediatelyAfterCustomEmoji(doc, selection.from)) {
                const nextPos = selection.from + 1;
                if (nextPos <= doc.content.size) {
                  moveSelection(view, nextPos);
                  event.preventDefault();
                  return true;
                }
              }

              return false;
            }

            if (event.key === "ArrowLeft") {
              if (isImmediatelyAfterCustomEmoji(doc, selection.from)) {
                const nodeBefore = selection.$from.nodeBefore;
                const prevPos = textNodeHasCustomEmojiMark(nodeBefore)
                  ? selection.from - nodeBefore!.nodeSize
                  : selection.from - 1;
                moveSelection(view, prevPos);
                event.preventDefault();
                return true;
              }
            }

            return false;
          },
        },
      }),
    ];
  },
});
