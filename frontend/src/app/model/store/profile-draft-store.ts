import { create } from "zustand";

import { buildProfileDiscardPatch } from "@/shared/lib/profileDiscard";
import { normalizeAiProfileConfig, snapshotAiConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import {
  normalizeChannelProfileConfig,
  normalizeTelegramProfileConfig,
} from "@/shared/lib/profile/normalizeProfileConfig";
import { telegramConfigSnapshot } from "@/shared/lib/profile/telegramSnapshot";
import { isChannelProfileDraftDirty } from "@/shared/lib/profile/channelProfileDraft";
import { createEmptyAccountStore } from "@/shared/data/empty-account-state";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  TelegramProfileConfig,
} from "@/shared/types";

function buildInitialAiSnapshot(cfg: AiProfileConfig): string {
  return JSON.stringify({
    llmModels: cfg.llmModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: !!m.includeInMulti,
    })),
    webSearchModels: cfg.webSearchModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: !!m.includeInMulti,
    })),
    visionModels: cfg.visionModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: false,
    })),
    imageGenerationModels: cfg.imageGenerationModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: false,
    })),
    orchestratorModels: cfg.orchestratorModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: false,
    })),
    webReasonerModels: cfg.webReasonerModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: false,
    })),
    ragReasonerModels: cfg.ragReasonerModels.map((m) => ({
      provider: m.provider || "",
      model: m.model || "",
      apiKey: m.apiKey || "",
      active: !!m.active,
      includeInMulti: false,
    })),
    multiResponseEnabled: !!cfg.multiResponseEnabled,
  });
}

function buildInitialTelegramSnapshot(cfg: TelegramProfileConfig): string {
  return JSON.stringify({
    apiId: cfg.apiId || "",
    apiHash: cfg.apiHash || "",
    phone: cfg.phone || "",
    sessionName: cfg.sessionName || "",
    channel: cfg.channel || "",
    botApiToken: cfg.botApiToken || "",
    botStatus: cfg.botStatus,
  });
}

export type ProfileDraftState = {
  aiProfileConfig: AiProfileConfig;
  channelProfileConfig: ChannelProfileConfig;
  telegramProfileConfig: TelegramProfileConfig;
  systemPromptSavedSnapshot: string;
  modelSettingsSavedSnapshot: string;
  channelProfileSavedSnapshot: string;
  telegramSettingsSavedSnapshot: string;
  hydrated: boolean;
  lastHydratedAccountId: string | null;
};

type ProfileSnapshotPatch = Partial<
  Pick<
    ProfileDraftState,
    | "systemPromptSavedSnapshot"
    | "modelSettingsSavedSnapshot"
    | "channelProfileSavedSnapshot"
    | "telegramSettingsSavedSnapshot"
  >
>;

type ProfileDraftActions = {
  hydrateFromServer: (
    accountId: string,
    channel: ChannelProfileConfig,
    ai: AiProfileConfig,
    telegram: TelegramProfileConfig,
  ) => void;
  updateChannelProfile: (config: ChannelProfileConfig) => void;
  updateAiConfig: (config: AiProfileConfig) => void;
  updateTelegramConfig: (config: TelegramProfileConfig) => void;
  applyPatch: (patch: ProfileSnapshotPatch) => void;
  discardEdits: () => void;
  resetForLogout: () => void;
};

function createInitialProfileDraftState(): ProfileDraftState {
  const empty = createEmptyAccountStore();
  return {
    aiProfileConfig: structuredClone(empty.aiProfile),
    channelProfileConfig: structuredClone(empty.channelProfile),
    telegramProfileConfig: structuredClone(empty.telegramProfile),
    systemPromptSavedSnapshot: empty.aiProfile.systemPrompt,
    modelSettingsSavedSnapshot: buildInitialAiSnapshot(empty.aiProfile),
    channelProfileSavedSnapshot: JSON.stringify(empty.channelProfile),
    telegramSettingsSavedSnapshot: buildInitialTelegramSnapshot(empty.telegramProfile),
    hydrated: false,
    lastHydratedAccountId: null,
  };
}

export const useProfileDraftStore = create<ProfileDraftState & ProfileDraftActions>((set, get) => ({
  ...createInitialProfileDraftState(),
  hydrateFromServer: (accountId, channel, ai, telegram) => {
    const state = get();
    const normalizedChannel = normalizeChannelProfileConfig(channel);
    const normalizedAi = normalizeAiProfileConfig(ai);
    const normalizedTelegram = normalizeTelegramProfileConfig(telegram);
    const accountChanged = state.lastHydratedAccountId !== accountId;
    const preserveChannelDraft =
      state.hydrated && !accountChanged && isChannelProfileDraftDirty(
        state.channelProfileConfig,
        state.channelProfileSavedSnapshot,
      );

    set({
      channelProfileConfig: preserveChannelDraft
        ? state.channelProfileConfig
        : structuredClone(normalizedChannel),
      aiProfileConfig: structuredClone(normalizedAi),
      telegramProfileConfig: structuredClone(normalizedTelegram),
      channelProfileSavedSnapshot: preserveChannelDraft
        ? state.channelProfileSavedSnapshot
        : JSON.stringify(normalizedChannel),
      modelSettingsSavedSnapshot: buildInitialAiSnapshot(normalizedAi),
      systemPromptSavedSnapshot: normalizedAi.systemPrompt,
      telegramSettingsSavedSnapshot: buildInitialTelegramSnapshot(normalizedTelegram),
      hydrated: true,
      lastHydratedAccountId: accountId,
    });
  },
  updateChannelProfile: (config) => set({ channelProfileConfig: config }),
  updateAiConfig: (config) => set({ aiProfileConfig: config }),
  updateTelegramConfig: (config) => set({ telegramProfileConfig: config }),
  applyPatch: (patch) => set(patch),
  discardEdits: () => {
    const state = get();
    const patch = buildProfileDiscardPatch(state);
    set({
      aiProfileConfig: patch.aiProfileConfig,
      channelProfileConfig: patch.channelProfileConfig,
      telegramProfileConfig: patch.telegramProfileConfig,
    });
  },
  resetForLogout: () => set(createInitialProfileDraftState()),
}));

export function selectChannelProfileConfig(state: ProfileDraftState) {
  return state.channelProfileConfig;
}

export function selectChannelProfileSavedSnapshot(state: ProfileDraftState) {
  return state.channelProfileSavedSnapshot;
}

export function selectAiProfileConfig(state: ProfileDraftState) {
  return state.aiProfileConfig;
}

export function selectModelSettingsSavedSnapshot(state: ProfileDraftState) {
  return state.modelSettingsSavedSnapshot;
}

export function selectProfileHydrated(state: ProfileDraftState) {
  return state.hydrated;
}

export function selectSystemPromptSavedSnapshot(state: ProfileDraftState) {
  return state.systemPromptSavedSnapshot;
}

export function selectTelegramProfileConfig(state: ProfileDraftState) {
  return state.telegramProfileConfig;
}

export function selectTelegramSettingsSavedSnapshot(state: ProfileDraftState) {
  return state.telegramSettingsSavedSnapshot;
}

export const domainActions = {
  updateChannelProfile: (config: ChannelProfileConfig) =>
    ({ type: "UPDATE_CHANNEL_PROFILE", config }) as const,
  updateAiConfig: (config: AiProfileConfig) => ({ type: "UPDATE_AI_CONFIG", config }) as const,
  updateTelegramConfig: (config: TelegramProfileConfig) =>
    ({ type: "UPDATE_TELEGRAM_CONFIG", config }) as const,
};

type DomainAction = ReturnType<
  (typeof domainActions)[keyof typeof domainActions]
>;

export function useDomainSelector<T>(selector: (state: ProfileDraftState) => T): T {
  return useProfileDraftStore(selector);
}

export function useDomainDispatch() {
  const updateChannelProfile = useProfileDraftStore((s) => s.updateChannelProfile);
  const updateAiConfig = useProfileDraftStore((s) => s.updateAiConfig);
  const updateTelegramConfig = useProfileDraftStore((s) => s.updateTelegramConfig);

  return (action: DomainAction) => {
    switch (action.type) {
      case "UPDATE_CHANNEL_PROFILE":
        updateChannelProfile(action.config);
        break;
      case "UPDATE_AI_CONFIG":
        updateAiConfig(action.config);
        break;
      case "UPDATE_TELEGRAM_CONFIG":
        updateTelegramConfig(action.config);
        break;
    }
  };
}

export function useDomainActions() {
  const applyPatch = useProfileDraftStore((s) => s.applyPatch);
  return { applyPatch };
}

export { snapshotAiConfig, telegramConfigSnapshot };
