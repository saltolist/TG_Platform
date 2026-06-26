import type { BlockNoteEditor } from "@blocknote/core";
import { describe, expect, it, vi } from "vitest";

import {
  isEmptyParagraphBlock,
  pruneExcessEmptyParagraphs,
} from "./noteDragCleanup";

describe("noteDragCleanup", () => {
  it("detects empty paragraph blocks", () => {
    expect(isEmptyParagraphBlock({ id: "1", type: "paragraph" })).toBe(true);
    expect(isEmptyParagraphBlock({ id: "2", type: "paragraph", content: [] })).toBe(
      true,
    );
    expect(
      isEmptyParagraphBlock({
        id: "3",
        type: "paragraph",
        content: [{ type: "text", text: "   " }],
      }),
    ).toBe(true);
    expect(
      isEmptyParagraphBlock({
        id: "4",
        type: "paragraph",
        content: [{ type: "text", text: "hi" }],
      }),
    ).toBe(false);
    expect(isEmptyParagraphBlock({ id: "5", type: "heading", content: [] })).toBe(
      false,
    );
  });

  it("removes new empty paragraphs left after drag", () => {
    const removeBlocks = vi.fn();
    const editor = {
      document: [
        { id: "orphan", type: "paragraph", content: [] },
        { id: "kept", type: "paragraph", content: [{ type: "text", text: "text" }] },
      ],
      removeBlocks,
    } as unknown as BlockNoteEditor;

    pruneExcessEmptyParagraphs(editor, [
      { id: "moved", empty: false },
      { id: "kept", empty: false },
    ]);

    expect(removeBlocks).toHaveBeenCalledWith(["orphan"]);
  });

  it("removes a block that became empty during drag", () => {
    const removeBlocks = vi.fn();
    const editor = {
      document: [
        { id: "was-filled", type: "paragraph", content: [] },
        { id: "kept", type: "paragraph", content: [{ type: "text", text: "ok" }] },
      ],
      removeBlocks,
    } as unknown as BlockNoteEditor;

    pruneExcessEmptyParagraphs(editor, [
      { id: "was-filled", empty: false },
      { id: "kept", empty: false },
    ]);

    expect(removeBlocks).toHaveBeenCalledWith(["was-filled"]);
  });
});
