import { describe, expect, it } from "vitest";

import { detectTelegramRevisionAdvance } from "./telegramRevisionPoll";

describe("detectTelegramRevisionAdvance", () => {
  it("detects metrics revision advance against a stale baseline", () => {
    const advance = detectTelegramRevisionAdvance(
      { metricsRevision: 3 },
      { syncRevision: 0, commentsRevision: 0, metricsRevision: 2 },
      null,
    );

    expect(advance.metricsRevisionAdvanced).toBe(true);
    expect(advance.syncRevisionAdvanced).toBe(false);
    expect(advance.commentsRevisionAdvanced).toBe(false);
  });

  it("does not treat equal revisions as advanced", () => {
    const advance = detectTelegramRevisionAdvance(
      { metricsRevision: 2, commentsRevision: 1, syncRevision: 5 },
      { syncRevision: 5, commentsRevision: 1, metricsRevision: 2 },
      "2026-07-03T10:00:00.000Z",
    );

    expect(advance.metricsRevisionAdvanced).toBe(false);
    expect(advance.commentsRevisionAdvanced).toBe(false);
    expect(advance.syncRevisionAdvanced).toBe(false);
    expect(advance.lastSyncAdvanced).toBe(false);
  });

  it("detects lastSync change when revisions are unchanged", () => {
    const advance = detectTelegramRevisionAdvance(
      { lastSync: "2026-07-03T10:01:00.000Z" },
      { syncRevision: 0, commentsRevision: 0, metricsRevision: 0 },
      "2026-07-03T10:00:00.000Z",
    );

    expect(advance.lastSyncAdvanced).toBe(true);
  });
});
