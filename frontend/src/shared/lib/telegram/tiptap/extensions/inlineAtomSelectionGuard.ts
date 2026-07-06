import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { NodeSelection, Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";

const TELEGRAM_EMOJI = "telegramEmoji";

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

function docSelectionHasFormatableText(doc: ProseMirrorNode, from: number, to: number): boolean {
  let hasFormatableText = false;

  doc.nodesBetween(from, to, (node) => {
    if (hasFormatableText) return false;
    if (node.type.name === TELEGRAM_EMOJI) return;
    if (node.isText && node.text) {
      hasFormatableText = true;
      return false;
    }
    return;
  });

  return hasFormatableText;
}

function selectionTouchesEmoji(doc: ProseMirrorNode, from: number, to: number): boolean {
  let touchesEmoji = false;

  doc.nodesBetween(from, to, (node) => {
    if (touchesEmoji) return false;
    if (node.type.name === TELEGRAM_EMOJI) {
      touchesEmoji = true;
      return false;
    }
    return;
  });

  return touchesEmoji;
}

function domSelectionIncludesEmojiNode(root: HTMLElement): boolean {
  const selection = root.ownerDocument.getSelection();
  if (!selection || selection.rangeCount === 0) return false;

  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    for (const node of [
      range.startContainer,
      range.endContainer,
      range.commonAncestorContainer,
    ]) {
      const element = node instanceof HTMLElement ? node : node.parentElement;
      if (element?.closest(".telegram-emoji-node")) return true;
    }
  }

  return false;
}

function skipEmojiNodeSelection(
  doc: ProseMirrorNode,
  selection: NodeSelection,
  direction: "forward" | "backward",
): TextSelection {
  const after = selection.from + selection.node.nodeSize;
  const before = selection.from;
  const pos = direction === "forward" ? after : before;
  return TextSelection.create(doc, pos);
}

function skipAdjacentEmoji(
  doc: ProseMirrorNode,
  $from: TextSelection["$from"],
  direction: "forward" | "backward",
): TextSelection | null {
  if (direction === "forward") {
    const nodeAfter = $from.nodeAfter;
    if (nodeAfter?.type.name !== TELEGRAM_EMOJI) return null;
    return TextSelection.create(doc, $from.pos + nodeAfter.nodeSize);
  }

  const nodeBefore = $from.nodeBefore;
  if (nodeBefore?.type.name !== TELEGRAM_EMOJI) return null;
  return TextSelection.create(doc, $from.pos - nodeBefore.nodeSize);
}

const inlineAtomSelectionGuardKey = new PluginKey("inlineAtomSelectionGuard");

/** Skip custom emoji atoms on arrow keys and prevent bogus node/DOM selections. */
export const InlineAtomSelectionGuard = Extension.create({
  name: "inlineAtomSelectionGuard",

  addProseMirrorPlugins() {
    let collapseAfterNavigation = false;

    return [
      new Plugin({
        key: inlineAtomSelectionGuardKey,
        props: {
          handleKeyDown(view, event) {
            if (event.shiftKey) return false;

            const { selection, doc } = view.state;

            if (event.key === "Backspace" && selection instanceof TextSelection && selection.empty) {
              const nodeBefore = selection.$from.nodeBefore;
              if (nodeBefore?.type.name === TELEGRAM_EMOJI) {
                view.dispatch(
                  view.state.tr.delete(selection.from - nodeBefore.nodeSize, selection.from).scrollIntoView(),
                );
                event.preventDefault();
                return true;
              }
            }

            if (event.key === "Delete" && selection instanceof TextSelection && selection.empty) {
              const nodeAfter = selection.$from.nodeAfter;
              if (nodeAfter?.type.name === TELEGRAM_EMOJI) {
                view.dispatch(
                  view.state.tr.delete(selection.from, selection.from + nodeAfter.nodeSize).scrollIntoView(),
                );
                event.preventDefault();
                return true;
              }
            }

            if (!isNavigationKey(event.key)) return false;
            const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
            const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";

            if (selection instanceof NodeSelection) {
              if (selection.node.type.name !== TELEGRAM_EMOJI) return false;
              view.dispatch(
                view.state.tr
                  .setSelection(skipEmojiNodeSelection(doc, selection, forward ? "forward" : "backward"))
                  .scrollIntoView(),
              );
              event.preventDefault();
              return true;
            }

            if (!(selection instanceof TextSelection) || !selection.empty) return false;

            const nextSelection = skipAdjacentEmoji(
              doc,
              selection.$from,
              forward ? "forward" : "backward",
            );
            if (!nextSelection) return false;

            view.dispatch(view.state.tr.setSelection(nextSelection).scrollIntoView());
            event.preventDefault();
            collapseAfterNavigation = true;
            return true;
          },
        },
        view(view) {
          const restoreCaret = () => {
            const { selection } = view.state;
            if (!(selection instanceof TextSelection) || !selection.empty) return;
            if (!domSelectionIncludesEmojiNode(view.dom)) return;

            view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, selection.head)));
          };

          view.dom.ownerDocument.addEventListener("selectionchange", restoreCaret);
          return {
            destroy() {
              view.dom.ownerDocument.removeEventListener("selectionchange", restoreCaret);
            },
          };
        },
        appendTransaction: (_transactions, _oldState, newState) => {
          const { selection, doc } = newState;

          if (selection instanceof NodeSelection && selection.node.type.name === TELEGRAM_EMOJI) {
            return newState.tr.setSelection(
              skipEmojiNodeSelection(doc, selection, "forward"),
            );
          }

          if (!(selection instanceof TextSelection) || selection.empty) {
            collapseAfterNavigation = false;
            return null;
          }

          const { from, to } = selection;
          const shouldCollapse =
            collapseAfterNavigation ||
            !docSelectionHasFormatableText(doc, from, to) ||
            (to - from === 1 && selectionTouchesEmoji(doc, from, to));

          collapseAfterNavigation = false;
          if (!shouldCollapse) return null;

          return newState.tr.setSelection(TextSelection.create(doc, selection.head));
        },
      }),
    ];
  },
});
