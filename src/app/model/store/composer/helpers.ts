import {
  buildMultiResponsePairs,
  formatWebSearchComposerLabel,
  VARIANT_TAILS,
} from "@/shared/config/composer";
import type { AiProfileConfig, AiVariant, ChatMessage, ComposerScope, LlmModel } from "@/shared/types";

export function resolveLlmLabel(cfg: AiProfileConfig, id: string): string {
  const model = cfg.llmModels.find((m) => m.id === id);
  return model ? `${model.provider} / ${model.model || "модель"}` : "LLM не выбрана";
}

export function resolveWebLabel(cfg: AiProfileConfig, id: string): string {
  if (!id) return "Нет";
  const model = cfg.webSearchModels.find((m) => m.id === id);
  return model
    ? formatWebSearchComposerLabel(model.provider, model.model || "модель")
    : "Нет";
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
): string | null {
  return (
    getLlmSendValidationMessage(cfg, scope, targetLlmId) ??
    getOrchestratorSendValidationMessage(cfg)
  );
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

export function buildAiReplyMessage(
  cfg: AiProfileConfig,
  baseReply: string,
  scope: ComposerScope,
  target: { llmId: string; webId: string },
): ChatMessage {
  if (cfg.multiResponseEnabled) {
    const pairs = buildMultiResponsePairs(cfg.llmModels, cfg.webSearchModels);
    if (pairs.length > 0) {
      const variants: AiVariant[] = pairs.map((pair, idx) => {
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
          text: `${baseReply}\n\n— ${label}\n${VARIANT_TAILS[idx % VARIANT_TAILS.length]}`,
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
    text: `${baseReply}\n\n— ${label}\n${VARIANT_TAILS[0]}`,
    mode: "single",
    targetLabel: label,
    llmLabel: llm,
    webLabel: web,
  };
}
