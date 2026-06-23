function copyTextViaExecCommand(text: string): boolean {
  if (typeof document === "undefined") return false;

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  Object.assign(textarea.style, {
    position: "fixed",
    top: "0",
    left: "0",
    width: "1px",
    height: "1px",
    opacity: "0",
    pointerEvents: "none",
  });

  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  } finally {
    document.body.removeChild(textarea);
  }

  return ok;
}

/** Copy plain text; falls back to ``execCommand`` when Clipboard API is unavailable. */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  const trimmed = text.trim();
  if (!trimmed) return false;

  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(trimmed);
      return true;
    } catch {
      // fall through to execCommand
    }
  }

  return copyTextViaExecCommand(trimmed);
}

/**
 * Copy text loaded asynchronously while preserving the user-gesture context.
 *
 * Uses ``ClipboardItem`` with a Promise payload when supported; otherwise loads
 * the text first and copies via ``copyTextToClipboard``.
 */
export async function copyTextToClipboardFromPromise(
  loadText: () => Promise<string>,
): Promise<boolean> {
  if (
    typeof ClipboardItem !== "undefined" &&
    typeof navigator !== "undefined" &&
    navigator.clipboard?.write
  ) {
    try {
      const blobPromise = loadText().then((text) => {
        const trimmed = text.trim();
        if (!trimmed) throw new Error("empty clipboard text");
        return new Blob([trimmed], { type: "text/plain" });
      });
      await navigator.clipboard.write([
        new ClipboardItem({ "text/plain": blobPromise }),
      ]);
      return true;
    } catch {
      // fall through
    }
  }

  try {
    const text = await loadText();
    return copyTextToClipboard(text);
  } catch {
    return false;
  }
}
