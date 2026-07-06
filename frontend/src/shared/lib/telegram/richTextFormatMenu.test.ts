import { describe, expect, it } from "vitest";

import {
  getRichTextFormatMenuPage,
  RICH_TEXT_FORMAT_MENU_ITEMS,
} from "./richTextFormatMenu";

describe("getRichTextFormatMenuPage", () => {
  it("shows first three formats with only next arrow", () => {
    const page = getRichTextFormatMenuPage(0);
    expect(page.items.map((item) => item.label)).toEqual([
      "Жирный",
      "Курсив",
      "Подчёркнутый",
    ]);
    expect(page.canGoPrev).toBe(false);
    expect(page.canGoNext).toBe(true);
  });

  it("shows middle page with both arrows", () => {
    const page = getRichTextFormatMenuPage(1);
    expect(page.items.map((item) => item.label)).toEqual([
      "Зачёркнутый",
      "Спойлер",
      "Код",
    ]);
    expect(page.canGoPrev).toBe(true);
    expect(page.canGoNext).toBe(true);
  });

  it("shows last page with only previous arrow", () => {
    const page = getRichTextFormatMenuPage(2);
    expect(page.items.map((item) => item.label)).toEqual(["Ссылка"]);
    expect(page.canGoPrev).toBe(true);
    expect(page.canGoNext).toBe(false);
  });

  it("clamps invalid page indexes", () => {
    const page = getRichTextFormatMenuPage(99);
    expect(page.page).toBe(2);
    expect(page.items).toHaveLength(1);
    expect(page.items[0]?.format).toBe(
      RICH_TEXT_FORMAT_MENU_ITEMS[RICH_TEXT_FORMAT_MENU_ITEMS.length - 1]?.format,
    );
  });
});
