import { Mark } from "@tiptap/core";

export const Spoiler = Mark.create({
  name: "spoiler",

  parseHTML() {
    return [{ tag: "span.tg-spoiler" }];
  },

  renderHTML() {
    return ["span", { class: "tg-spoiler" }, 0];
  },
});
