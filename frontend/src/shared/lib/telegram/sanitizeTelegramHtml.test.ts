/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import { sanitizeTelegramHtml } from "./sanitizeTelegramHtml";

describe("sanitizeTelegramHtml", () => {
  it("keeps Telegram formatting tags", () => {
    expect(sanitizeTelegramHtml("<strong>bold</strong> and <s>strike</s>")).toBe(
      "<strong>bold</strong> and <s>strike</s>",
    );
  });

  it("strips script tags", () => {
    expect(sanitizeTelegramHtml('<strong>ok</strong><script>alert(1)</script>')).toBe(
      "<strong>ok</strong>",
    );
  });

  it("allows safe links only", () => {
    expect(
      sanitizeTelegramHtml(
        '<a href="https://example.com">site</a><a href="javascript:alert(1)">bad</a>',
      ),
    ).toBe(
      '<a href="https://example.com" rel="noopener noreferrer" target="_blank">site</a>bad',
    );
  });

  it("preserves spoiler spans", () => {
    expect(sanitizeTelegramHtml('<span class="tg-spoiler">secret</span>')).toBe(
      '<span class="tg-spoiler">secret</span>',
    );
  });
});
