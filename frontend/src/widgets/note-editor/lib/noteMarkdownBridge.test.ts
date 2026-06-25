import { describe, expect, it } from "vitest";

import {
  attachmentMarkdown,
  resolveAttachmentsToUrls,
  restoreUrlsToAttachments,
} from "@/widgets/note-editor/lib/noteMarkdownBridge";
import type { NoteFile } from "@/shared/types";

const imageFile: NoteFile = {
  id: "img1",
  name: "Скриншот",
  type: "image/png",
  url: "blob:http://localhost/abc-123",
};

const docFile: NoteFile = {
  id: "doc1",
  name: "Отчёт",
  type: "application/pdf",
  url: "https://cdn.example.com/files/report.pdf?sig=a&b=1",
};

const files = [imageFile, docFile];

describe("attachmentMarkdown", () => {
  it("builds image markdown for image files", () => {
    expect(attachmentMarkdown(imageFile)).toBe("![Скриншот](attachment:img1)");
  });

  it("builds link markdown for non-image files", () => {
    expect(attachmentMarkdown(docFile)).toBe("[Отчёт](attachment:doc1)");
  });
});

describe("resolveAttachmentsToUrls", () => {
  it("resolves image and file attachments to their urls", () => {
    const body = "![Скриншот](attachment:img1)\n\n[Отчёт](attachment:doc1)";
    expect(resolveAttachmentsToUrls(body, files)).toBe(
      `![Скриншот](${imageFile.url})\n\n[Отчёт](${docFile.url})`,
    );
  });

  it("leaves unknown attachment ids untouched", () => {
    const body = "[X](attachment:missing)";
    expect(resolveAttachmentsToUrls(body, files)).toBe(body);
  });

  it("does not touch plain external links", () => {
    const body = "[site](https://example.com)";
    expect(resolveAttachmentsToUrls(body, files)).toBe(body);
  });
});

describe("restoreUrlsToAttachments", () => {
  it("restores urls back to attachment ids (incl. query params)", () => {
    const exported = `![Скриншот](${imageFile.url})\n\n[Отчёт](${docFile.url})`;
    expect(restoreUrlsToAttachments(exported, files)).toBe(
      "![Скриншот](attachment:img1)\n\n[Отчёт](attachment:doc1)",
    );
  });
});

describe("round-trip", () => {
  it("import -> export preserves the canonical attachment format", () => {
    const original = "# Заметка\n\n![Скриншот](attachment:img1)\n\nТекст [Отчёт](attachment:doc1) тут.";
    const resolved = resolveAttachmentsToUrls(original, files);
    const restored = restoreUrlsToAttachments(resolved, files);
    expect(restored).toBe(original);
  });
});
