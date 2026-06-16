import { describe, expect, it } from "vitest";

import { caretIndexFromTextareaGeometry } from "@/widgets/note-editor/lib/noteBodyCanvasFocus";

describe("caretIndexFromTextareaGeometry", () => {
  const lineHeight = 10;
  const charWidth = 8;
  const measure = (line: string, charIndex: number) => charIndex * charWidth;

  it("returns 0 for empty value", () => {
    expect(caretIndexFromTextareaGeometry("", 5, 5, lineHeight, measure)).toBe(0);
  });

  it("places caret at start of first line", () => {
    expect(caretIndexFromTextareaGeometry("hello", 2, 0, lineHeight, measure)).toBe(0);
  });

  it("places caret by X on a single line", () => {
    expect(caretIndexFromTextareaGeometry("hello", 2, 20, lineHeight, measure)).toBe(2);
  });

  it("moves to second line by Y", () => {
    const value = "abc\ndef";
    expect(caretIndexFromTextareaGeometry(value, 15, 8, lineHeight, measure)).toBe(5);
  });

  it("clamps index to value length", () => {
    expect(caretIndexFromTextareaGeometry("hi", 999, 999, lineHeight, measure)).toBe(2);
  });
});
