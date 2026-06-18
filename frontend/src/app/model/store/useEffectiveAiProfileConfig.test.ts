import { describe, expect, it } from "vitest";

import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import type { AiProfileConfig } from "@/shared/types";

function pickEffectiveAiProfile(
  draft: AiProfileConfig,
  aiFromQuery: AiProfileConfig | undefined,
): AiProfileConfig {
  if (draft.llmModels.length > 0) return draft;
  if (!aiFromQuery) return draft;
  return normalizeAiProfileConfig(aiFromQuery);
}

describe("effective AI profile for composer", () => {
  it("uses query data while draft llmModels are still empty", () => {
    const draft: AiProfileConfig = {
      llmModels: [],
      webSearchModels: [],
      visionModels: [],
      imageGenerationModels: [],
      orchestratorModels: [],
      webReasonerModels: [],
      ragReasonerModels: [],
      multiResponseEnabled: false,
      systemPrompt: "",
    };
    const fromQuery: AiProfileConfig = {
      ...draft,
      llmModels: [
        {
          id: "llm-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "sk-openai-demo",
          active: true,
          includeInMulti: false,
        },
      ],
    };

    const effective = pickEffectiveAiProfile(draft, fromQuery);
    expect(effective.llmModels).toHaveLength(1);
    expect(effective.llmModels[0]?.provider).toBe("OpenAI");
  });

  it("keeps draft when models are already hydrated", () => {
    const draft: AiProfileConfig = {
      llmModels: [
        {
          id: "llm-overlay",
          provider: "DeepSeek",
          model: "deepseek-chat",
          apiKey: "sk-real",
          active: true,
          includeInMulti: false,
        },
      ],
      webSearchModels: [],
      visionModels: [],
      imageGenerationModels: [],
      orchestratorModels: [],
      webReasonerModels: [],
      ragReasonerModels: [],
      multiResponseEnabled: false,
      systemPrompt: "",
    };
    const fromQuery: AiProfileConfig = {
      ...draft,
      llmModels: [
        {
          id: "llm-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "sk-openai-demo",
          active: true,
          includeInMulti: false,
        },
      ],
    };

    const effective = pickEffectiveAiProfile(draft, fromQuery);
    expect(effective.llmModels[0]?.id).toBe("llm-overlay");
  });
});
