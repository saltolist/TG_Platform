import type { AiProfileConfig, LlmModel } from "@/shared/types";

type AiModelSnapshot = {
  provider: string;
  model: string;
  apiKey: string;
  active: boolean;
  includeInMulti: boolean;
};

export function normalizeAiProfileConfig(cfg: AiProfileConfig): AiProfileConfig {
  return {
    ...cfg,
    visionModels: cfg.visionModels ?? [],
    imageGenerationModels: cfg.imageGenerationModels ?? [],
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
  const modelSnapshot = (m: LlmModel): AiModelSnapshot => ({
    provider: m.provider || "",
    model: m.model || "",
    apiKey: m.apiKey || "",
    active: !!m.active,
    includeInMulti: !!m.includeInMulti,
  });

  return JSON.stringify({
    llmModels: cfg.llmModels.map(modelSnapshot),
    webSearchModels: cfg.webSearchModels.map(modelSnapshot),
    visionModels: cfg.visionModels.map(modelSnapshot),
    imageGenerationModels: cfg.imageGenerationModels.map(modelSnapshot),
    orchestratorModels: normalizeExclusiveModels(cfg.orchestratorModels).map(modelSnapshot),
    webReasonerModels: normalizeExclusiveModels(cfg.webReasonerModels).map(modelSnapshot),
    ragReasonerModels: normalizeExclusiveModels(cfg.ragReasonerModels).map(modelSnapshot),
    multiResponseEnabled: !!cfg.multiResponseEnabled,
  });
}
