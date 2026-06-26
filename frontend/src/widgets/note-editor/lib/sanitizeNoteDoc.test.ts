import { describe, expect, it } from "vitest";

import { sanitizeNoteDoc } from "./sanitizeNoteDoc";

describe("sanitizeNoteDoc", () => {
  it("flattens legacy column blocks into supported blocks", () => {
    const doc = [
      {
        type: "columnList",
        children: [
          {
            type: "column",
            children: [
              {
                type: "paragraph",
                content: [{ type: "text", text: "Left" }],
              },
            ],
          },
          {
            type: "column",
            children: [
              {
                type: "paragraph",
                content: [{ type: "text", text: "Right" }],
              },
            ],
          },
        ],
      },
    ];

    expect(sanitizeNoteDoc(doc)).toEqual([
      { type: "paragraph", content: [{ type: "text", text: "Left", styles: {} }] },
      { type: "paragraph", content: [{ type: "text", text: "Right", styles: {} }] },
    ]);
  });

  it("converts unknown block types with text into paragraphs", () => {
    const doc = [
      {
        type: "customWidget",
        content: [{ type: "text", text: "Hello" }],
      },
    ];

    expect(sanitizeNoteDoc(doc)).toEqual([
      { type: "paragraph", content: [{ type: "text", text: "Hello", styles: {} }] },
    ]);
  });

  it("keeps supported blocks unchanged", () => {
    const doc = [
      {
        type: "heading",
        props: { level: 2 },
        content: [{ type: "text", text: "Title" }],
      },
    ];

    expect(sanitizeNoteDoc(doc)).toEqual([
      {
        type: "heading",
        props: { level: 2 },
        content: [{ type: "text", text: "Title", styles: {} }],
      },
    ]);
  });

  it("promotes invalid nested list children to paragraphs", () => {
    const doc = [
      {
        type: "bulletListItem",
        content: [{ type: "text", text: "Item" }],
        children: [
          {
            type: "paragraph",
            content: [{ type: "text", text: "Nested paragraph" }],
          },
        ],
      },
    ];

    expect(sanitizeNoteDoc(doc)).toEqual([
      {
        type: "bulletListItem",
        content: [{ type: "text", text: "Item", styles: {} }],
      },
      { type: "paragraph", content: [{ type: "text", text: "Nested paragraph", styles: {} }] },
    ]);
  });

  it("preserves table content and strips invalid table children", () => {
    const tableContent = {
      type: "tableContent",
      rows: [{ cells: [[{ type: "text", text: "A", styles: {} }]] }],
    };
    const doc = [
      {
        type: "table",
        content: tableContent,
        children: [{ type: "paragraph", content: [{ type: "text", text: "bad" }] }],
      },
    ];

    expect(sanitizeNoteDoc(doc)).toEqual([
      {
        type: "table",
        content: tableContent,
      },
    ]);
  });
});
