import { describe, expect, it } from "vitest";

import { isChannelProfileDraftDirty } from "@/shared/lib/profile/channelProfileDraft";
import { createEmptyChannelProfile } from "@/shared/data/empty-account-state";

describe("isChannelProfileDraftDirty", () => {
  it("returns false when draft matches saved snapshot", () => {
    const cfg = createEmptyChannelProfile();
    cfg.voice.tone = "Деловой";
    const snapshot = JSON.stringify(cfg);
    expect(isChannelProfileDraftDirty(cfg, snapshot)).toBe(false);
  });

  it("returns true when tone changed", () => {
    const saved = createEmptyChannelProfile();
    const current = structuredClone(saved);
    current.voice.tone = "Деловой";
    expect(isChannelProfileDraftDirty(current, JSON.stringify(saved))).toBe(true);
  });
});
