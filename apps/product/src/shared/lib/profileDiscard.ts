import type { AiProfileConfig, ChannelProfileConfig, LlmModel, TelegramProfileConfig } from "@/shared/types";

type AiModelSnapshot = {
  provider: string;
  model: string;
  apiKey: string;
  active: boolean;
  includeInMulti: boolean;
};

type AiSettingsSnapshot = {
  llmModels: AiModelSnapshot[];
  webSearchModels: AiModelSnapshot[];
  visionModels?: AiModelSnapshot[];
  imageGenerationModels?: AiModelSnapshot[];
  orchestratorModels: AiModelSnapshot[];
  webReasonerModels: AiModelSnapshot[];
  ragReasonerModels: AiModelSnapshot[];
  multiResponseEnabled: boolean;
};

function normalizeExclusiveModels(models: LlmModel[]): LlmModel[] {
  let activeSeen = false;
  return models.map((model) => {
    const active = !!model.active && !activeSeen;
    if (active) activeSeen = true;
    return { ...model, active, includeInMulti: false };
  });
}

export function restoreAiConfigFromSnapshot(
  current: AiProfileConfig,
  snapshotJson: string,
): AiProfileConfig {
  const saved = JSON.parse(snapshotJson) as AiSettingsSnapshot;
  const currentModelSnapshot = (model: LlmModel): AiModelSnapshot => ({
    provider: model.provider || "",
    model: model.model || "",
    apiKey: model.apiKey || "",
    active: !!model.active,
    includeInMulti: false,
  });
  const mapModels = (
    currentModels: LlmModel[],
    savedModels: AiModelSnapshot[],
    idPrefix: string,
  ): LlmModel[] =>
    savedModels.map((row, i) => ({
      id: currentModels[i]?.id ?? `${idPrefix}-${Date.now()}-${i}`,
      provider: row.provider,
      model: row.model,
      apiKey: row.apiKey,
      active: row.active,
      includeInMulti: row.includeInMulti,
    }));

  return {
    ...current,
    llmModels: mapModels(current.llmModels, saved.llmModels, "llm"),
    webSearchModels: mapModels(current.webSearchModels, saved.webSearchModels, "web"),
    visionModels: mapModels(
      current.visionModels,
      saved.visionModels ?? current.visionModels.map(currentModelSnapshot),
      "vision",
    ),
    imageGenerationModels: mapModels(
      current.imageGenerationModels,
      saved.imageGenerationModels ?? current.imageGenerationModels.map(currentModelSnapshot),
      "image-gen",
    ),
    orchestratorModels: normalizeExclusiveModels(
      mapModels(
        current.orchestratorModels,
        saved.orchestratorModels ?? current.orchestratorModels.map(currentModelSnapshot),
        "orchestrator",
      ),
    ),
    webReasonerModels: normalizeExclusiveModels(
      mapModels(
        current.webReasonerModels,
        saved.webReasonerModels ?? current.webReasonerModels.map(currentModelSnapshot),
        "web-reasoner",
      ),
    ),
    ragReasonerModels: normalizeExclusiveModels(
      mapModels(
        current.ragReasonerModels,
        saved.ragReasonerModels ?? current.ragReasonerModels.map(currentModelSnapshot),
        "rag-reasoner",
      ),
    ),
    multiResponseEnabled: saved.multiResponseEnabled,
  };
}

function parseTelegramSavedFields(snapshotJson: string): Pick<
  TelegramProfileConfig,
  "apiId" | "apiHash" | "phone" | "sessionName" | "channel" | "botApiToken" | "botStatus"
> {
  try {
    const saved = JSON.parse(snapshotJson) as Partial<TelegramProfileConfig>;
    return {
      apiId: saved.apiId || "",
      apiHash: saved.apiHash || "",
      phone: saved.phone || "",
      sessionName: saved.sessionName || "",
      channel: saved.channel || "",
      botApiToken: saved.botApiToken || "",
      botStatus: saved.botStatus ?? "idle",
    };
  } catch {
    return {
      apiId: "",
      apiHash: "",
      phone: "",
      sessionName: "",
      channel: "",
      botApiToken: "",
      botStatus: "idle",
    };
  }
}

export function restoreTelegramConfigFromSnapshot(
  current: TelegramProfileConfig,
  snapshotJson: string,
): TelegramProfileConfig {
  return { ...current, ...parseTelegramSavedFields(snapshotJson) };
}

export function buildProfileDiscardPatch(input: {
  aiProfileConfig: AiProfileConfig;
  channelProfileConfig: ChannelProfileConfig;
  telegramProfileConfig: TelegramProfileConfig;
  systemPromptSavedSnapshot: string;
  modelSettingsSavedSnapshot: string;
  channelProfileSavedSnapshot: string;
  telegramSettingsSavedSnapshot: string;
}): Pick<StateProfileFields, keyof StateProfileFields> {
  const aiRestored = restoreAiConfigFromSnapshot(
    input.aiProfileConfig,
    input.modelSettingsSavedSnapshot,
  );
  return {
    aiProfileConfig: {
      ...aiRestored,
      systemPrompt: input.systemPromptSavedSnapshot,
    },
    channelProfileConfig: JSON.parse(
      input.channelProfileSavedSnapshot,
    ) as ChannelProfileConfig,
    telegramProfileConfig: restoreTelegramConfigFromSnapshot(
      input.telegramProfileConfig,
      input.telegramSettingsSavedSnapshot,
    ),
  };
}

type StateProfileFields = {
  aiProfileConfig: AiProfileConfig;
  channelProfileConfig: ChannelProfileConfig;
  telegramProfileConfig: TelegramProfileConfig;
};
