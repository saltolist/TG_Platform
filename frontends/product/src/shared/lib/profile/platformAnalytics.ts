import { hashString, buildTrend } from "@/shared/lib/trendChart/math";
import { PLATFORM_MODEL_TYPE_OPTIONS, type ModelTypeId } from "@/shared/lib/platformModelFilters";
import type { AiProfileConfig, LlmModel } from "@/shared/types";

export const MODEL_LINE_COLORS = [
  "#3d7cff",
  "#4caf82",
  "#e8954a",
  "#9b7cdb",
  "#e85a5a",
  "#35b8d4",
  "#d7a935",
  "#7ccf68",
  "#c778dd",
  "#6f9dfb",
] as const;

export type PlatformModelUsage = {
  id: string;
  label: string;
  role: string;
  type: ModelTypeId;
  active: boolean;
  calls: number;
  tokens: number;
  cost: number;
  success: number;
  latency: number;
  share: number;
  trend: number[];
  color: string;
};

export type PlatformModelUsageTotals = {
  calls: number;
  tokens: number;
  cost: number;
  success: number;
};

export function getTrendPointCost(model: PlatformModelUsage, index: number) {
  const value = model.trend[index] ?? 0;
  const ratio = model.calls > 0 ? value / model.calls : 0;
  return model.cost * ratio;
}

export function buildModelUsage(
  config: AiProfileConfig,
  periodMultiplier: number,
  trendPointCount = 7,
): PlatformModelUsage[] {
  const models = [
    ...mapConfigModels(config.llmModels, "llm", "LLM"),
    ...mapConfigModels(config.webSearchModels, "web", "Web Search"),
    ...mapConfigModels(config.visionModels, "vision", "Компьютерное зрение"),
    ...mapConfigModels(config.imageGenerationModels, "imageGeneration", "Генерация изображений"),
    ...mapConfigModels(config.orchestratorModels, "orchestrator", "Оркестратор"),
    ...mapConfigModels(config.webReasonerModels, "webReasoner", "Web Reasoner"),
    ...mapConfigModels(config.ragReasonerModels, "ragReasoner", "RAG Reasoner"),
  ];

  const usage = models.map((model) => {
    const seed = hashString(`${model.id}:${model.label}:${model.role}`);
    const baseCalls = 130 + (seed % 760);
    const activityBoost = model.active ? 1 : 0.36;
    const calls = Math.round(baseCalls * periodMultiplier * activityBoost);
    const tokensPerCall = 640 + (seed % 1900);
    const trend = buildTrend(seed, calls, trendPointCount);

    return {
      ...model,
      calls,
      tokens: Math.round(calls * tokensPerCall),
      cost: calls * tokensPerCall * (0.0000018 + (seed % 7) * 0.00000022),
      success: 91 + (seed % 8),
      latency: 620 + (seed % 740),
      share: 0,
      trend,
      color: "",
    };
  });

  const totalsByType = usage.reduce<Record<ModelTypeId, number>>(
    (acc, model) => ({ ...acc, [model.type]: acc[model.type] + model.calls }),
    { llm: 0, web: 0, vision: 0, imageGeneration: 0, orchestrator: 0, webReasoner: 0, ragReasoner: 0 },
  );

  return usage
    .map((model) => ({
      ...model,
      share: totalsByType[model.type] > 0 ? Math.round((model.calls / totalsByType[model.type]) * 100) : 0,
    }))
    .sort((a, b) => b.calls - a.calls)
    .map((model, i) => ({
      ...model,
      color: MODEL_LINE_COLORS[i % MODEL_LINE_COLORS.length] as string,
    }));
}

function mapConfigModels(models: LlmModel[], type: ModelTypeId, role: string) {
  return models
    .filter((model) => model.provider && model.model)
    .map((model) => ({
      id: `${type}-${role}-${model.id}`,
      label: `${model.provider} / ${model.model}`,
      role,
      type,
      active: model.active,
    }));
}

export function buildTypeUsage(models: PlatformModelUsage[]): PlatformModelUsage[] {
  const totalCalls = models.reduce((sum, model) => sum + model.calls, 0);

  return PLATFORM_MODEL_TYPE_OPTIONS.flatMap((type, i) => {
    const typeRows = models.filter((model) => model.type === type.id);
    if (typeRows.length === 0) return [];

    const calls = typeRows.reduce((sum, model) => sum + model.calls, 0);
    const tokens = typeRows.reduce((sum, model) => sum + model.tokens, 0);
    const cost = typeRows.reduce((sum, model) => sum + model.cost, 0);
    const latency =
      calls > 0
        ? Math.round(typeRows.reduce((sum, model) => sum + model.latency * model.calls, 0) / calls)
        : 0;
    const success =
      calls > 0
        ? Math.round(typeRows.reduce((sum, model) => sum + model.success * model.calls, 0) / calls)
        : 0;
    const trendLength = Math.max(...typeRows.map((model) => model.trend.length), 0);
    const trend = Array.from({ length: trendLength }, (_, trendIndex) =>
      typeRows.reduce((sum, model) => sum + (model.trend[trendIndex] ?? 0), 0),
    );

    return [
      {
        id: `type-${type.id}`,
        label: type.label,
        role: "Тип моделей",
        type: type.id,
        active: typeRows.some((model) => model.active),
        calls,
        tokens,
        cost,
        success,
        latency,
        share: totalCalls > 0 ? Math.round((calls / totalCalls) * 100) : 0,
        trend,
        color: MODEL_LINE_COLORS[i % MODEL_LINE_COLORS.length],
      },
    ];
  });
}

export function summarizeModelUsage(models: PlatformModelUsage[]): PlatformModelUsageTotals {
  const calls = models.reduce((sum, model) => sum + model.calls, 0);
  const tokens = models.reduce((sum, model) => sum + model.tokens, 0);
  const cost = models.reduce((sum, model) => sum + model.cost, 0);
  const success =
    calls > 0
      ? Math.round(models.reduce((sum, model) => sum + model.success * model.calls, 0) / calls)
      : 0;

  return { calls, tokens, cost, success };
}
