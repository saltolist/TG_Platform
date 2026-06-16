import type { LlmModel } from "@/shared/types";

export function modelPairKey(provider: string, model: string): string {
  return `${provider}\u0000${model}`;
}

export function listTakenModelPairs(models: LlmModel[], excludeIndex: number): Set<string> {
  const taken = new Set<string>();
  models.forEach((row, index) => {
    if (index === excludeIndex) return;
    const provider = row.provider?.trim();
    const model = row.model?.trim();
    if (!provider || !model) return;
    taken.add(modelPairKey(provider, model));
  });
  return taken;
}

export function filterAvailableModels(
  providerMap: Record<string, string[]>,
  models: LlmModel[],
  rowIndex: number,
  provider: string,
): string[] {
  if (!provider) return [];
  const taken = listTakenModelPairs(models, rowIndex);
  return (providerMap[provider] ?? []).filter((model) => !taken.has(modelPairKey(provider, model)));
}

export function filterAvailableProviders(
  providerMap: Record<string, string[]>,
  models: LlmModel[],
  rowIndex: number,
): string[] {
  const taken = listTakenModelPairs(models, rowIndex);
  return Object.keys(providerMap).filter((provider) =>
    (providerMap[provider] ?? []).some((model) => !taken.has(modelPairKey(provider, model))),
  );
}

export function hasAvailableModelSlots(
  providerMap: Record<string, string[]>,
  models: LlmModel[],
): boolean {
  const taken = listTakenModelPairs(models, -1);
  for (const [provider, modelList] of Object.entries(providerMap)) {
    for (const model of modelList) {
      if (!taken.has(modelPairKey(provider, model))) return true;
    }
  }
  return false;
}
