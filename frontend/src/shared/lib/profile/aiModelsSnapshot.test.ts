import { describe, expect, it } from "vitest";

import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";

describe("normalizeAiProfileConfig", () => {
  it("fills empty API profile objects with safe defaults", () => {
    const normalized = normalizeAiProfileConfig({});

    expect(normalized.llmModels).toEqual([]);
    expect(normalized.webSearchModels).toEqual([]);
    expect(normalized.visionModels).toEqual([]);
    expect(normalized.imageGenerationModels).toEqual([]);
    expect(normalized.orchestratorModels).toEqual([]);
    expect(normalized.webReasonerModels).toEqual([]);
    expect(normalized.ragReasonerModels).toEqual([]);
    expect(normalized.multiResponseEnabled).toBe(false);
    expect(normalized.systemPrompt).toBe("");
  });
});
