import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveNoteFileDisplayUrl } from "@/widgets/note-editor/lib/noteFileDisplayUrl";
import type { NoteFile } from "@/shared/types";

const files: NoteFile[] = [
  { id: "img1", name: "shot.png", type: "image/png", url: "data:image/png;base64,abc" },
];

describe("resolveNoteFileDisplayUrl", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves attachment ids from the file registry", async () => {
    await expect(resolveNoteFileDisplayUrl("attachment:img1", files)).resolves.toBe(files[0]!.url);
  });

  it("returns unknown attachment ids unchanged", async () => {
    await expect(resolveNoteFileDisplayUrl("attachment:missing", files)).resolves.toBe(
      "attachment:missing",
    );
  });

  it("passes through https urls", async () => {
    await expect(resolveNoteFileDisplayUrl("https://cdn.test/a.png", files)).resolves.toBe(
      "https://cdn.test/a.png",
    );
  });

  it("converts data urls to blob urls on webkit safari", async () => {
    vi.stubGlobal("navigator", {
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        blob: async () => new Blob(["x"], { type: "image/png" }),
      })),
    );
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:note-test"),
    });

    await expect(resolveNoteFileDisplayUrl("data:image/png;base64,abc", files)).resolves.toBe(
      "blob:note-test",
    );
  });
});
