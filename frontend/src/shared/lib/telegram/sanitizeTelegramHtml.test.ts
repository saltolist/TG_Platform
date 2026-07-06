/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import {
  renderTelegramHtmlForDisplay,
  sanitizeTelegramHtml,
} from "./sanitizeTelegramHtml";

describe("sanitizeTelegramHtml tg-emoji", () => {
  it("preserves tg-emoji with emoji-id", () => {
    const html = '<tg-emoji emoji-id="12345">⭐</tg-emoji> hello';
    expect(sanitizeTelegramHtml(html)).toBe(
      '<tg-emoji emoji-id="12345">⭐</tg-emoji> hello',
    );
  });

  it("renders custom emoji placeholders for hydration", () => {
    const html = '<tg-emoji emoji-id="999">⭐</tg-emoji>';
    const rendered = renderTelegramHtmlForDisplay(html);
    expect(rendered).toContain('class="tg-custom-emoji');
    expect(rendered).toContain('data-emoji-id="999"');
    expect(rendered).toContain("⭐");
    expect(rendered).not.toContain("<img");
  });
});
