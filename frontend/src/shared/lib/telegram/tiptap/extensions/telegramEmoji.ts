import { mergeAttributes, Node } from "@tiptap/core";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    telegramEmoji: {
      insertTelegramEmoji: (attrs: { documentId: string; alt?: string }) => ReturnType;
    };
  }
}

export const TelegramEmoji = Node.create({
  name: "telegramEmoji",
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
        parseHTML: (element) => element.textContent?.trim() || "⭐",
      },
    };
  },

  parseHTML() {
    return [{ tag: "tg-emoji" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return [
      "tg-emoji",
      mergeAttributes(HTMLAttributes, { "emoji-id": node.attrs.documentId }),
      node.attrs.alt,
    ];
  },

  renderText({ node }) {
    return node.attrs.alt ?? "⭐";
  },

  addCommands() {
    return {
      insertTelegramEmoji:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: {
              documentId: attrs.documentId,
              alt: attrs.alt ?? "⭐",
            },
          }),
    };
  },
});
