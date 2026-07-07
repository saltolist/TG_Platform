import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

const TELEGRAM_CUSTOM_EMOJI = "telegramCustomEmoji";

function createCaretStrut(): HTMLElement {
  const span = document.createElement("span");
  span.className = "telegram-emoji-caret-strut";
  span.textContent = "\u200b";
  span.setAttribute("aria-hidden", "true");
  return span;
}

function needsCaretStrutBefore(doc: ProseMirrorNode, pos: number): boolean {
  const $pos = doc.resolve(pos);
  const before = $pos.nodeBefore;
  if (!before) return true;
  if (before.type.name === TELEGRAM_CUSTOM_EMOJI) return false;
  if (before.isText) return false;
  return true;
}

function needsCaretStrutAfter(doc: ProseMirrorNode, pos: number): boolean {
  const $pos = doc.resolve(pos);
  const after = $pos.nodeAfter;
  if (!after) return true;
  if (after.type.name === TELEGRAM_CUSTOM_EMOJI) return false;
  if (after.isText) return false;
  return true;
}

const customEmojiCaretStrutsKey = new PluginKey("customEmojiCaretStruts");

/** Zero-width struts at emoji edges so the caret keeps normal text height. */
export const CustomEmojiCaretStruts = Extension.create({
  name: "customEmojiCaretStruts",

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: customEmojiCaretStrutsKey,
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];

            state.doc.descendants((node, pos) => {
              if (node.type.name !== TELEGRAM_CUSTOM_EMOJI) return;

              if (needsCaretStrutBefore(state.doc, pos)) {
                decorations.push(
                  Decoration.widget(pos, createCaretStrut, {
                    side: -1,
                    key: `emoji-strut-before-${pos}`,
                  }),
                );
              }

              const afterPos = pos + node.nodeSize;
              if (needsCaretStrutAfter(state.doc, afterPos)) {
                decorations.push(
                  Decoration.widget(afterPos, createCaretStrut, {
                    side: -1,
                    key: `emoji-strut-after-${pos}`,
                  }),
                );
              }
            });

            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});
