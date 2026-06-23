/**
 * @vitest-environment jsdom
 */
import { BlockNoteEditor, BlockNoteSchema } from "@blocknote/core";
import { withMultiColumn } from "@blocknote/xl-multi-column";
import { describe, expect, it } from "vitest";

import type { NoteFile } from "@/shared/types";

import {
  flattenImageColumnLists,
  promoteImageRunsToColumnLists,
} from "./noteBlockLayout";
import {
  attachmentMarkdown,
  compactAttachmentImageRows,
  resolveAttachmentsToUrls,
  resolveUrlsToAttachments,
} from "./noteMarkdownBridge";

const imageA: NoteFile = {
  id: "img-a",
  name: "a.png",
  type: "image/png",
  url: "https://cdn.example.com/a.png",
};

const imageB: NoteFile = {
  id: "img-b",
  name: "b.png",
  type: "image/png",
  url: "https://cdn.example.com/b.png",
};

const imageC: NoteFile = {
  id: "img-c",
  name: "c.png",
  type: "image/png",
  url: "https://cdn.example.com/c.png",
};

function createEditor() {
  return BlockNoteEditor.create({ schema: withMultiColumn(BlockNoteSchema.create()) });
}

function imageBlock(url: string, name: string) {
  return {
    type: "image" as const,
    props: { url, name, caption: "", showPreview: true },
  };
}

describe("compactAttachmentImageRows", () => {
  it("removes blank lines between consecutive image lines", () => {
    const input = [
      "![a](attachment:img-a)",
      "",
      "",
      "![b](attachment:img-b)",
      "",
      "![c](attachment:img-c)",
    ].join("\n");
    expect(compactAttachmentImageRows(input)).toBe(
      ["![a](attachment:img-a)", "![b](attachment:img-b)", "![c](attachment:img-c)"].join("\n"),
    );
  });

  it("preserves blank lines around text and between text and images", () => {
    const input = [
      "![a](attachment:img-a)",
      "",
      "Paragraph",
      "",
      "![b](attachment:img-b)",
    ].join("\n");
    expect(compactAttachmentImageRows(input)).toBe(input);
  });
});

describe("noteBlockLayout", () => {
  it("promotes 3 consecutive images into columnList", () => {
    const blocks = [imageBlock("https://x/a.png", "a"), imageBlock("https://x/b.png", "b"), imageBlock("https://x/c.png", "c")];
    const promoted = promoteImageRunsToColumnLists(blocks);
    expect(promoted).toHaveLength(1);
    expect(promoted[0]?.type).toBe("columnList");
    expect(promoted[0]?.children).toHaveLength(3);
  });

  it("leaves a single image as-is", () => {
    const blocks = [imageBlock("https://x/a.png", "a")];
    const promoted = promoteImageRunsToColumnLists(blocks);
    expect(promoted).toHaveLength(1);
    expect(promoted[0]?.type).toBe("image");
  });

  it("flattens image-only columnList back to images", () => {
    const columnList = {
      type: "columnList" as const,
      children: [
        { type: "column" as const, props: { width: 1 }, children: [imageBlock("https://x/a.png", "a")] },
        { type: "column" as const, props: { width: 1 }, children: [imageBlock("https://x/b.png", "b")] },
      ],
    };
    const flat = flattenImageColumnLists([columnList]);
    expect(flat).toHaveLength(2);
    expect(flat.every((b) => b.type === "image")).toBe(true);
  });

  it("round-trips columnList through flatten and compact markdown", () => {
    const columnList = promoteImageRunsToColumnLists([
      imageBlock("https://cdn.example.com/a.png", imageA.name),
      imageBlock("https://cdn.example.com/b.png", imageB.name),
      imageBlock("https://cdn.example.com/c.png", imageC.name),
    ]);
    const flat = flattenImageColumnLists(columnList);
    const editor = createEditor();
    const markdown = compactAttachmentImageRows(
      resolveUrlsToAttachments(editor.blocksToMarkdownLossy(flat), [imageA, imageB, imageC]),
    ).trimEnd();
    expect(markdown).toBe(
      [attachmentMarkdown(imageA), attachmentMarkdown(imageB), attachmentMarkdown(imageC)].join("\n"),
    );
  });
});

describe("noteMarkdownBridge integration", () => {
  it("resolves attachment ids to urls on import", () => {
    const body = "![photo](attachment:img-a)\n\n[report](attachment:doc-1)";
    const resolved = resolveAttachmentsToUrls(body, [imageA]);
    expect(resolved).toContain("](https://cdn.example.com/a.png)");
  });

  it("full pipeline produces view-ready markdown from BlockNote image export", () => {
    const editor = createEditor();
    const resolved = resolveAttachmentsToUrls(
      [attachmentMarkdown(imageA), attachmentMarkdown(imageB), attachmentMarkdown(imageC)].join("\n\n"),
      [imageA, imageB, imageC],
    );
    const parsed = editor.tryParseMarkdownToBlocks(resolved);
    const promoted = promoteImageRunsToColumnLists(parsed);
    const flat = flattenImageColumnLists(promoted);
    const markdown = compactAttachmentImageRows(
      resolveUrlsToAttachments(editor.blocksToMarkdownLossy(flat), [imageA, imageB, imageC]),
    ).trimEnd();
    expect(markdown).toBe(
      [attachmentMarkdown(imageA), attachmentMarkdown(imageB), attachmentMarkdown(imageC)].join("\n"),
    );
  });
});
