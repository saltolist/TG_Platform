import { describe, expect, it } from "vitest";

import {
  resolveDocAttachments,
  restoreDocAttachments,
} from "@/widgets/note-editor/lib/noteDocAttachments";
import type { NoteFile } from "@/shared/types";

const files: NoteFile[] = [
  { id: "img1", name: "Скриншот", type: "image/png", url: "blob:http://localhost/abc" },
  { id: "doc1", name: "Отчёт", type: "application/pdf", url: "https://cdn.test/r.pdf?s=1" },
];

const storedDoc = [
  { type: "image", props: { url: "attachment:img1" }, children: [] },
  {
    type: "paragraph",
    content: [
      { type: "text", text: "см. " },
      { type: "link", href: "attachment:doc1", content: [{ type: "text", text: "Отчёт" }] },
    ],
  },
];

describe("resolveDocAttachments", () => {
  it("replaces attachment ids with resolvable urls", () => {
    const resolved = resolveDocAttachments(storedDoc, files) as typeof storedDoc;
    expect(resolved[0]?.props?.url).toBe(files[0]!.url);
    const link = (resolved[1]?.content as Array<{ type: string; href?: string }>)[1];
    expect(link?.href).toBe(files[1]!.url);
  });

  it("leaves unknown ids untouched", () => {
    const doc = [{ type: "image", props: { url: "attachment:missing" } }];
    expect(resolveDocAttachments(doc, files)).toEqual(doc);
  });

  it("does not mutate the input", () => {
    const snapshot = JSON.parse(JSON.stringify(storedDoc));
    resolveDocAttachments(storedDoc, files);
    expect(storedDoc).toEqual(snapshot);
  });
});

describe("restoreDocAttachments", () => {
  it("replaces resolvable urls back with attachment ids", () => {
    const resolved = resolveDocAttachments(storedDoc, files);
    const restored = restoreDocAttachments(resolved, files);
    expect(restored).toEqual(storedDoc);
  });

  it("ignores plain external urls", () => {
    const doc = [
      { type: "paragraph", content: [{ type: "link", href: "https://example.com", content: [] }] },
    ];
    expect(restoreDocAttachments(doc, files)).toEqual(doc);
  });
});
