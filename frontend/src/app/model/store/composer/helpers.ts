import {
  buildMultiResponsePairs,
  formatWebSearchComposerLabel,
} from "@/shared/config/composer";
import { getApiErrorMessage } from "@/shared/api/getApiErrorMessage";
import { isAbortError } from "@/shared/lib/isAbortError";
import { apiKeyForClientRequest } from "@/shared/lib/profile/maskedApiKey";
import type { AiProfileConfig, AiVariant, ChatMessage, ComposerScope, LlmModel } from "@/shared/types";
import type { WebCite } from "@/shared/api/schemas/post";

export { applyStreamingAiText, applyStreamingAiVariantText } from "@/shared/lib/chatPaths";

export function resolveLlmLabel(cfg: AiProfileConfig, id: string): string {
  const model = cfg.llmModels.find((m) => m.id === id);
  return model ? `${model.provider} / ${model.model || "модель"}` : "LLM не выбрана";
}

export const EMPTY_AI_REPLY_FALLBACK =
  "Не удалось получить ответ от модели. Проверьте API ключ и настройки провайдера.";

export async function completeAssistantReply(
  stream: () => Promise<string>,
  onError?: (message: string) => void,
  options?: { allowEmpty?: boolean },
): Promise<string> {
  try {
    const text = await stream();
    const trimmed = text.trim();
    if (!trimmed) {
      if (options?.allowEmpty) return text;
      onError?.(EMPTY_AI_REPLY_FALLBACK);
      return EMPTY_AI_REPLY_FALLBACK;
    }
    return text;
  } catch (error) {
    if (isAbortError(error)) return "";
    const message = getApiErrorMessage(error, EMPTY_AI_REPLY_FALLBACK);
    onError?.(message);
    return message;
  }
}

export function pickWebCites(...sources: (WebCite[] | undefined)[]): WebCite[] | undefined {
  for (const source of sources) {
    if (source && source.length > 0) return source;
  }
  return undefined;
}

/** Merge per-variant web cites from finalize payload and streaming cache. */
export function mergeVariantWebCites(
  message: ChatMessage | null | undefined,
  variantWebCites?: Record<string, WebCite[]>,
): Record<string, WebCite[]> | undefined {
  const merged: Record<string, WebCite[]> = {};
  if (variantWebCites) {
    for (const [key, cites] of Object.entries(variantWebCites)) {
      if (cites.length > 0) merged[key] = cites;
    }
  }
  if (message?.variants) {
    for (const variant of message.variants) {
      if (variant.webCites?.length && !merged[variant.key]?.length) {
        merged[variant.key] = variant.webCites;
      }
    }
  }
  return Object.keys(merged).length > 0 ? merged : undefined;
}

export async function completeStreamedAssistantReply(
  stream: () => Promise<{ text: string; webCites: WebCite[] }>,
  onError?: (message: string) => void,
  options?: { allowEmpty?: boolean },
): Promise<{ text: string; webCites: WebCite[] }> {
  let webCites: WebCite[] = [];
  const text = await completeAssistantReply(
    async () => {
      const result = await stream();
      webCites = result.webCites;
      return result.text;
    },
    onError,
    options,
  );
  return { text, webCites };
}

export function resolveLlmApiKey(cfg: AiProfileConfig, llmId: string): string | undefined {
  return resolveLlmTarget(cfg, llmId).apiKey;
}

export function resolveLlmTarget(
  cfg: AiProfileConfig,
  llmId: string,
): { llmId: string; provider?: string; model?: string; apiKey?: string } {
  const selected = llmId
    ? cfg.llmModels.find((item) => item.id === llmId)
    : cfg.llmModels.find((item) => item.active) ?? cfg.llmModels[0];
  if (!selected) return { llmId };
  const provider = selected.provider?.trim();
  const model = selected.model?.trim();
  const apiKey = apiKeyForClientRequest(selected.apiKey);
  return {
    llmId: selected.id,
    provider: provider || undefined,
    model: model || undefined,
    apiKey: apiKey || undefined,
  };
}

export function resolveWebLabel(cfg: AiProfileConfig, id: string): string {
  if (!id) return "Нет";
  const model = cfg.webSearchModels.find((m) => m.id === id);
  return model
    ? formatWebSearchComposerLabel(model.provider, model.model || "модель")
    : "Нет";
}

export function resolveWebTarget(
  cfg: AiProfileConfig,
  webId: string,
): { webId: string; webProvider?: string; webModel?: string; webApiKey?: string } | null {
  if (!webId) return null;
  const selected = cfg.webSearchModels.find((m) => m.id === webId);
  if (!selected) return null;
  const provider = selected.provider?.trim();
  const model = selected.model?.trim();
  const apiKey = apiKeyForClientRequest(selected.apiKey);
  return {
    webId: selected.id,
    webProvider: provider || undefined,
    webModel: model || undefined,
    webApiKey: apiKey || undefined,
  };
}

export function hasConfiguredModel(models: LlmModel[]): boolean {
  return models.some((model) => !!model.provider?.trim() && !!model.model?.trim());
}

export function hasActiveConfiguredModel(models: LlmModel[]): boolean {
  return models.some((model) => !!model.provider?.trim() && !!model.model?.trim() && model.active);
}

function isConfiguredModel(model: LlmModel): boolean {
  return !!model.provider?.trim() && !!model.model?.trim();
}

export function getLlmSendValidationMessage(
  cfg: AiProfileConfig,
  scope: ComposerScope,
  targetLlmId: string,
): string | null {
  if (hasLlmForComposerScope(cfg, scope, targetLlmId)) return null;
  if (!hasConfiguredModel(cfg.llmModels)) return "Добавьте LLM модель.";

  if (cfg.multiResponseEnabled) {
    return "Активируйте LLM модель.";
  }

  if (!targetLlmId) return "Выберите LLM модель.";
  const selected = cfg.llmModels.find((model) => model.id === targetLlmId);
  if (selected && isConfiguredModel(selected) && !selected.active) {
    return "Активируйте LLM модель.";
  }
  return "Добавьте LLM модель.";
}

export function getOrchestratorSendValidationMessage(cfg: AiProfileConfig): string | null {
  if (hasActiveConfiguredModel(cfg.orchestratorModels)) return null;
  if (hasConfiguredModel(cfg.orchestratorModels)) return "Активируйте модель оркестратора.";
  return "Добавьте модель оркестратора.";
}

export function getChatSendValidationMessage(
  cfg: AiProfileConfig,
  scope: ComposerScope,
  targetLlmId: string,
  options?: { requireOrchestrator?: boolean },
): string | null {
  const llmMessage = getLlmSendValidationMessage(cfg, scope, targetLlmId);
  if (llmMessage) return llmMessage;
  if (options?.requireOrchestrator === false) return null;
  return getOrchestratorSendValidationMessage(cfg);
}

export function hasLlmForComposerScope(
  cfg: AiProfileConfig,
  scope: ComposerScope,
  targetLlmId: string,
): boolean {
  if (cfg.multiResponseEnabled) {
    return cfg.llmModels.some((m) => m.provider && m.model && m.active && m.includeInMulti);
  }
  if (!targetLlmId) return false;
  return cfg.llmModels.some(
    (m) => m.id === targetLlmId && !!m.provider?.trim() && !!m.model?.trim() && m.active,
  );
}

export function buildStreamingAiShell(
  cfg: AiProfileConfig,
  target: { llmId: string; webId: string },
): ChatMessage {
  if (cfg.multiResponseEnabled) {
    const pairs = buildMultiResponsePairs(cfg.llmModels, cfg.webSearchModels);
    if (pairs.length > 0) {
      const variants: AiVariant[] = pairs.map((pair) => {
        const llmModel = cfg.llmModels.find((m) => m.id === pair.llmId);
        const webModel = pair.webId
          ? cfg.webSearchModels.find((m) => m.id === pair.webId)
          : undefined;
        const llmCap = llmModel ? `${llmModel.provider}/${llmModel.model}` : "";
        const webCap = webModel
          ? formatWebSearchComposerLabel(webModel.provider, webModel.model)
          : "";
        const label = webCap ? `${llmCap} + ${webCap}` : llmCap;
        return {
          key: pair.id,
          label,
          llmCaption: llmCap,
          webCaption: webCap || undefined,
          text: "",
        };
      });
      return { role: "ai", variants, selectedVariant: 0, mode: "multi", streaming: true };
    }
  }
  const llm = resolveLlmLabel(cfg, target.llmId);
  const web = resolveWebLabel(cfg, target.webId);
  const label = target.webId ? `${llm} + ${web}` : llm;
  return {
    role: "ai",
    text: "",
    mode: "single",
    targetLabel: label,
    llmLabel: llm,
    webLabel: web,
    streaming: true,
  };
}

export function buildAiReplyMessage(
  cfg: AiProfileConfig,
  baseReply: string,
  scope: ComposerScope,
  target: { llmId: string; webId: string },
  variantTexts?: Record<string, string>,
  webCites?: WebCite[],
  variantWebCites?: Record<string, WebCite[]>,
): ChatMessage {
  if (cfg.multiResponseEnabled) {
    const pairs = buildMultiResponsePairs(cfg.llmModels, cfg.webSearchModels);
    if (pairs.length > 0) {
      const variants: AiVariant[] = pairs.map((pair) => {
        const llmModel = cfg.llmModels.find((m) => m.id === pair.llmId);
        const webModel = pair.webId
          ? cfg.webSearchModels.find((m) => m.id === pair.webId)
          : undefined;
        const llmCap = llmModel ? `${llmModel.provider}/${llmModel.model}` : "";
        const webCap = webModel
          ? formatWebSearchComposerLabel(webModel.provider, webModel.model)
          : "";
        const label = webCap ? `${llmCap} + ${webCap}` : llmCap;
        const pairWebCites = variantWebCites?.[pair.id];
        return {
          key: pair.id,
          label,
          llmCaption: llmCap,
          webCaption: webCap || undefined,
          text: variantTexts?.[pair.id] ?? baseReply,
          ...(pairWebCites?.length ? { webCites: pairWebCites } : {}),
        };
      });
      return { role: "ai", variants, selectedVariant: 0, mode: "multi" };
    }
  }
  const llm = resolveLlmLabel(cfg, target.llmId);
  const web = resolveWebLabel(cfg, target.webId);
  const label = target.webId ? `${llm} + ${web}` : llm;
  return {
    role: "ai",
    text: baseReply,
    mode: "single",
    targetLabel: label,
    llmLabel: llm,
    webLabel: web,
    ...(webCites?.length ? { webCites } : {}),
  };
}
