import { Mark, mergeAttributes } from "@tiptap/core";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    telegramCustomEmoji: {
      insertTelegramEmoji: (attrs: { documentId: string; alt?: string }) => ReturnType;
    };
  }
}

export const TelegramCustomEmoji = Mark.create({
  name: "telegramCustomEmoji",
  inclusive: false,

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
    };
  },

  parseHTML() {
    return [{ tag: "tg-emoji[emoji-id]" }];
  },

  renderHTML({ mark, HTMLAttributes }) {
    return [
      "tg-emoji",
      mergeAttributes(HTMLAttributes, { "emoji-id": mark.attrs.documentId }),
      0,
    ];
  },

  addCommands() {
    return {
      insertTelegramEmoji:
        (attrs) =>
        ({ chain }) => {
          const alt = attrs.alt ?? "⭐";
          return chain()
            .insertContent({
              type: "text",
              text: alt,
              marks: [
                {
                  type: this.name,
                  attrs: { documentId: attrs.documentId },
                },
              ],
            })
            .run();
        },
    };
  },
});
