import { mergeAttributes, Node } from "@tiptap/core";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    telegramCustomEmoji: {
      insertTelegramEmoji: (attrs: { documentId: string; alt?: string }) => ReturnType;
    };
  }
}

export const TelegramCustomEmoji = Node.create({
  name: "telegramCustomEmoji",
  group: "inline",
  inline: true,
  atom: true,
  selectable: false,

  addAttributes() {
    return {
      documentId: {
        default: null,
        parseHTML: (element) => element.getAttribute("emoji-id"),
        renderHTML: (attributes) => {
          if (!attributes.documentId) return {};
          return { "emoji-id": attributes.documentId };
        },
      },
      alt: {
        default: "⭐",
        parseHTML: (element) => element.textContent ?? "⭐",
      },
    };
  },

  parseHTML() {
    return [{ tag: "tg-emoji[emoji-id]" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return [
      "tg-emoji",
      mergeAttributes(HTMLAttributes, { "emoji-id": node.attrs.documentId }),
      node.attrs.alt ?? "⭐",
    ];
  },

  renderText({ node }) {
    return node.attrs.alt ?? "⭐";
  },

  addCommands() {
    return {
      insertTelegramEmoji:
        (attrs) =>
        ({ chain }) => {
          if (!attrs.documentId) return false;
          return chain()
            .insertContent({
              type: this.name,
              attrs: {
                documentId: attrs.documentId,
                alt: attrs.alt ?? "⭐",
              },
            })
            .run();
        },
    };
  },
});
