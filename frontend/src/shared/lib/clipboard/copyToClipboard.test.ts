/**
 * @vitest-environment jsdom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  copyTextToClipboard,
  copyTextToClipboardFromPromise,
} from "@/shared/lib/clipboard/copyToClipboard";

describe("copyToClipboard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("copyTextToClipboard uses writeText when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await expect(copyTextToClipboard("secret-key")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("secret-key");
  });

  it("copyTextToClipboard falls back to execCommand", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;

    await expect(copyTextToClipboard("secret-key")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("copyTextToClipboardFromPromise uses ClipboardItem when supported", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    class MockClipboardItem {
      constructor(public items: Record<string, Promise<Blob>>) {}
    }
    vi.stubGlobal("ClipboardItem", MockClipboardItem);
    vi.stubGlobal("navigator", { clipboard: { write } });

    const loadText = vi.fn().mockResolvedValue("revealed-key");
    await expect(copyTextToClipboardFromPromise(loadText)).resolves.toBe(true);
    expect(write).toHaveBeenCalledTimes(1);
    expect(loadText).toHaveBeenCalledTimes(1);
  });

  it("copyTextToClipboardFromPromise loads text when ClipboardItem is unavailable", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    const loadText = vi.fn().mockResolvedValue("revealed-key");

    await expect(copyTextToClipboardFromPromise(loadText)).resolves.toBe(true);
    expect(loadText).toHaveBeenCalledTimes(1);
  });
});
