import { describe, expect, it } from "vitest";

import { bodyToEditLines, parseEmbedNameFromEditable, updateEmbedCell } from "@/shared/lib/noteEmbeds/textEdit";
import { splitLineHighlightParts } from "@/shared/lib/noteEmbeds/lineHighlight";

describe("parseEmbedNameFromEditable", () => {
  it("parses bracketed token", () => {
    expect(parseEmbedNameFromEditable("[photo.jpg]")).toBe("photo.jpg");
  });

  it("parses bare filename", () => {
    expect(parseEmbedNameFromEditable("doc.pdf")).toBe("doc.pdf");
  });

  it("trims whitespace", () => {
    expect(parseEmbedNameFromEditable("  [a.png]  ")).toBe("a.png");
  });
});

describe("bodyToEditLines", () => {
  it("splits body into one text line per newline", () => {
    const lines = bodyToEditLines("hello\n[file.jpg]");
    expect(lines).toHaveLength(2);
    expect(lines[0]?.cells[0]).toEqual({ type: "text", content: "hello" });
    expect(lines[1]?.cells[0]).toEqual({ type: "text", content: "[file.jpg]" });
  });
});

describe("splitLineHighlightParts", () => {
  it("marks embed tokens", () => {
    expect(splitLineHighlightParts("a [b.png] c")).toEqual([
      { type: "text", value: "a " },
      { type: "embed", value: "[b.png]" },
      { type: "text", value: " c" },
    ]);
  });
});

describe("updateEmbedCell", () => {
  it("updates embed name at position", () => {
    const lines = [{ cells: [{ type: "embed" as const, name: "old.jpg" }] }];
    const next = updateEmbedCell(lines, { line: 0, cell: 0 }, "new.jpg");
    expect(next[0]?.cells[0]).toEqual({ type: "embed", name: "new.jpg" });
  });
});
