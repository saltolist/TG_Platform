import type { AiProfileConfig, LlmModel } from "@/shared/types";

type AiModelSnapshot = {
  provider: string;
  model: string;
  apiKey: string;
  active: boolean;
  includeInMulti: boolean;
};

export function normalizeAiProfileConfig(
  cfg: Partial<AiProfileConfig> | null | undefined,
): AiProfileConfig {
  return {
    llmModels: cfg?.llmModels ?? [],
    webSearchModels: cfg?.webSearchModels ?? [],
    visionModels: cfg?.visionModels ?? [],
    imageGenerationModels: cfg?.imageGenerationModels ?? [],
    orchestratorModels: cfg?.orchestratorModels ?? [],
    webReasonerModels: cfg?.webReasonerModels ?? [],
    ragReasonerModels: cfg?.ragReasonerModels ?? [],
    multiResponseEnabled: !!cfg?.multiResponseEnabled,
    systemPrompt: cfg?.systemPrompt ?? "",
  };
}

export function normalizeExclusiveModels(models: LlmModel[]): LlmModel[] {
  let activeSeen = false;
  return models.map((model) => {
    const active = !!model.active && !activeSeen;
    if (active) activeSeen = true;
    return { ...model, active, includeInMulti: false };
  });
}

export function updateExclusiveModel(
  models: LlmModel[],
  idx: number,
  patch: Partial<LlmModel>,
): LlmModel[] {
  return models.map((model, i) => {
    if (i === idx) return { ...model, ...patch, includeInMulti: false };
    if (patch.active) return { ...model, active: false, includeInMulti: false };
    return { ...model, includeInMulti: false };
  });
}

export function snapshotAiConfig(cfg: AiProfileConfig) {
  const normalized = normalizeAiProfileConfig(cfg);
  const modelSnapshot = (m: LlmModel): AiModelSnapshot => ({
    provider: m.provider || "",
    model: m.model || "",
    apiKey: m.apiKey || "",
    active: !!m.active,
    includeInMulti: !!m.includeInMulti,
  });

  return JSON.stringify({
    llmModels: normalized.llmModels.map(modelSnapshot),
    webSearchModels: normalized.webSearchModels.map(modelSnapshot),
    visionModels: normalized.visionModels.map(modelSnapshot),
    imageGenerationModels: normalized.imageGenerationModels.map(modelSnapshot),
    orchestratorModels: normalizeExclusiveModels(normalized.orchestratorModels).map(modelSnapshot),
    webReasonerModels: normalizeExclusiveModels(normalized.webReasonerModels).map(modelSnapshot),
    ragReasonerModels: normalizeExclusiveModels(normalized.ragReasonerModels).map(modelSnapshot),
    multiResponseEnabled: !!normalized.multiResponseEnabled,
  });
}
