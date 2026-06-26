import { describe, expect, it } from "vitest";

import { isBlobUrl } from "@/widgets/note-editor/lib/noteFilePersistence";

describe("isBlobUrl", () => {
  it("detects blob urls", () => {
    expect(isBlobUrl("blob:http://localhost/abc")).toBe(true);
    expect(isBlobUrl("data:image/png;base64,abc")).toBe(false);
    expect(isBlobUrl("https://cdn.test/a.png")).toBe(false);
    expect(isBlobUrl(undefined)).toBe(false);
  });
});
