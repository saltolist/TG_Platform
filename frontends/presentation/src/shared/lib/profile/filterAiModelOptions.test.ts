import { describe, expect, it } from "vitest";

import {
  filterAvailableModels,
  filterAvailableProviders,
  hasAvailableModelSlots,
} from "@/shared/lib/profile/filterAiModelOptions";
import type { LlmModel } from "@/shared/types";

const providerMap = {
  OpenAI: ["gpt-4o", "gpt-4.1"],
  Anthropic: ["claude-3-7-sonnet"],
};

function row(provider: string, model: string): LlmModel {
  return {
    id: `${provider}-${model}`,
    provider,
    model,
    apiKey: "",
    active: true,
    includeInMulti: false,
  };
}

describe("filterAiModelOptions", () => {
  it("hides models already chosen in other rows", () => {
    const models = [row("OpenAI", "gpt-4o"), row("", "")];
    expect(filterAvailableModels(providerMap, models, 1, "OpenAI")).toEqual(["gpt-4.1"]);
  });

  it("hides providers with no free models left", () => {
    const models = [row("Anthropic", "claude-3-7-sonnet"), row("", "")];
    expect(filterAvailableProviders(providerMap, models, 1)).toEqual(["OpenAI"]);
  });

  it("keeps the current row selection available in its own selectors", () => {
    const models = [row("OpenAI", "gpt-4o"), row("OpenAI", "gpt-4.1")];
    expect(filterAvailableModels(providerMap, models, 0, "OpenAI")).toEqual(["gpt-4o"]);
    expect(filterAvailableProviders(providerMap, models, 0)).toEqual(["OpenAI", "Anthropic"]);
  });

  it("disables add when every provider/model pair is used", () => {
    const models = [row("OpenAI", "gpt-4o"), row("OpenAI", "gpt-4.1"), row("Anthropic", "claude-3-7-sonnet")];
    expect(hasAvailableModelSlots(providerMap, models)).toBe(false);
  });
});
