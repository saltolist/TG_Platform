import { describe, expect, it } from "vitest";

import {
  normalizeChannelProfileConfig,
  normalizeTelegramProfileConfig,
} from "@/shared/lib/profile/normalizeProfileConfig";

describe("normalizeProfileConfig", () => {
  it("fills channel defaults for empty server payload", () => {
    const cfg = normalizeChannelProfileConfig({});
    expect(cfg.core.topic).toBe("");
    expect(cfg.rubrics).toEqual([]);
  });

  it("fills telegram defaults for empty server payload", () => {
    const cfg = normalizeTelegramProfileConfig({});
    expect(cfg.authStatus).toBe("idle");
    expect(cfg.botApiToken).toBe("");
    expect(cfg.channel).toBe("");
  });
});
