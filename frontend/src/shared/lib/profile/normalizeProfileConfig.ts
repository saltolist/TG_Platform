import type {
  AiProfileConfig,
  ChannelProfileConfig,
  TelegramProfileConfig,
} from "@/shared/types";
import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import {
  createEmptyChannelProfile,
  createEmptyTelegramProfile,
} from "@/shared/data/empty-account-state";

export function normalizeChannelProfileConfig(
  cfg: Partial<ChannelProfileConfig> | null | undefined,
): ChannelProfileConfig {
  const base = createEmptyChannelProfile();
  if (!cfg) return base;
  return {
    core: { ...base.core, ...cfg.core },
    voice: { ...base.voice, ...cfg.voice },
    rules: { ...base.rules, ...cfg.rules },
    rubrics: Array.isArray(cfg.rubrics) ? cfg.rubrics : [],
  };
}

export function normalizeTelegramProfileConfig(
  cfg: Partial<TelegramProfileConfig> | null | undefined,
): TelegramProfileConfig {
  const base = createEmptyTelegramProfile();
  if (!cfg) return base;
  return { ...base, ...cfg };
}

export function normalizeAiProfileConfigFromServer(
  cfg: Partial<AiProfileConfig> | null | undefined,
): AiProfileConfig {
  return normalizeAiProfileConfig(cfg);
}
