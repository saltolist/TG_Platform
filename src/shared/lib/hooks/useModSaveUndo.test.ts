import { describe, expect, it, vi } from "vitest";

import { blockBrowserUndoWhenFieldStackEmpty } from "@/shared/lib/hooks/useModSaveUndo";

function editableTarget(tagName: string) {
  return { tagName, isContentEditable: false } as unknown as HTMLElement;
}

describe("useModSaveUndo helpers", () => {
  it("prevents default when field undo stack is empty", () => {
    const preventDefault = vi.fn();
    const event = {
      defaultPrevented: false,
      preventDefault,
      target: editableTarget("TEXTAREA"),
    } as unknown as KeyboardEvent;

    vi.stubGlobal("document", {
      queryCommandEnabled: () => false,
    });

    blockBrowserUndoWhenFieldStackEmpty(event);
    expect(preventDefault).toHaveBeenCalledTimes(1);

    vi.unstubAllGlobals();
  });

  it("keeps native undo when field undo stack is available", () => {
    const preventDefault = vi.fn();
    const event = {
      defaultPrevented: false,
      preventDefault,
      target: editableTarget("TEXTAREA"),
    } as unknown as KeyboardEvent;

    vi.stubGlobal("document", {
      queryCommandEnabled: () => true,
    });

    blockBrowserUndoWhenFieldStackEmpty(event);
    expect(preventDefault).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it("ignores non-editable targets", () => {
    const preventDefault = vi.fn();
    const event = {
      defaultPrevented: false,
      preventDefault,
      target: { tagName: "BUTTON", isContentEditable: false },
    } as unknown as KeyboardEvent;

    blockBrowserUndoWhenFieldStackEmpty(event);
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
