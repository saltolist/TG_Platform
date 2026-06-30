export const LLM_PROVIDER_MODELS: Record<string, string[]> = {
  OpenAI: ["gpt-4o", "gpt-4.1", "gpt-4.1-mini"],
  Perplexity: ["sonar", "sonar-pro"],
  Anthropic: ["claude-3-7-sonnet", "claude-3-5-sonnet"],
  Mistral: ["mistral-large", "mistral-small"],
  Google: ["gemini-1.5-pro", "gemini-1.5-flash"],
  DeepSeek: ["deepseek-chat", "deepseek-reasoner"],
  OpenRouter: [
    "meta-llama/llama-3.1-70b-instruct",
    "qwen/qwen-2.5-72b-instruct",
  ],
};

export const WEB_SEARCH_PROVIDER_MODELS: Record<string, string[]> = {
  Perplexity: ["search-api"],
  OpenAI: ["responses-api-web-search"],
  Tavily: ["search-v1"],
  SerpAPI: ["google-search"],
  Exa: ["exa-neural"],
};

export const VISION_PROVIDER_MODELS: Record<string, string[]> = {
  OpenAI: ["gpt-4o", "gpt-4.1"],
  Anthropic: ["claude-3-7-sonnet", "claude-3-5-sonnet"],
  Google: ["gemini-1.5-pro", "gemini-1.5-flash"],
};

export const IMAGE_GENERATION_PROVIDER_MODELS: Record<string, string[]> = {
  OpenAI: ["dall-e-3", "gpt-image-1"],
  Stability: ["stable-image-ultra", "stable-image-core"],
  Google: ["imagen-3"],
};

export const OPENAI_WEB_SEARCH_MODEL = "responses-api-web-search";
export const PERPLEXITY_WEB_SEARCH_MODEL = "search-api";

export function isOpenAiWebSearchModel(provider: string, model: string): boolean {
  return provider === "OpenAI" && model === OPENAI_WEB_SEARCH_MODEL;
}

export function isPerplexityWebSearchModel(provider: string, model: string): boolean {
  return provider === "Perplexity" && model === PERPLEXITY_WEB_SEARCH_MODEL;
}

/**
 * Supported web search providers in this iteration.
 * Tavily / SerpAPI / Exa are hidden until their standalone retrieval path is implemented.
 */
const ACTIVE_WEB_SEARCH_PROVIDERS = new Set(["OpenAI", "Perplexity"]);

export function isWebSearchProviderSupported(provider: string): boolean {
  return ACTIVE_WEB_SEARCH_PROVIDERS.has(provider);
}

export function formatWebSearchComposerLabel(provider: string, model: string): string {
  if (isOpenAiWebSearchModel(provider, model)) {
    return `${provider} / responses-api + web search`;
  }
  return `${provider} / ${model}`;
}

/** Короткая подпись на кнопке селектора (меню — полный formatWebSearchComposerLabel). */
export function formatWebSearchComposerButtonLabel(provider: string, model: string): string {
  if (isOpenAiWebSearchModel(provider, model)) {
    return "responses-api + web search";
  }
  return model;
}

export function formatLlmComposerButtonLabel(model: string): string {
  return model;
}

/**
 * Матрица видимости web-моделей для выбранного LLM:
 * - OpenAI responses-api только с OpenAI LLM
 * - Perplexity search-api только с не-Perplexity LLM (когда LLM=Perplexity — поиск встроен)
 * - Прочие скрыты до реализации
 */
export function isWebSearchVisibleForLlm(
  web: { provider: string; model: string },
  llm: { provider: string } | undefined,
): boolean {
  if (!isWebSearchProviderSupported(web.provider)) return false;
  if (isOpenAiWebSearchModel(web.provider, web.model)) return llm?.provider === "OpenAI";
  if (isPerplexityWebSearchModel(web.provider, web.model)) return llm?.provider !== "Perplexity";
  return true;
}

/**
 * Когда LLM=Perplexity — web-поиск встроен, отдельный селектор не нужен.
 * В этом случае возвращаем true и принудительно скрываем web-пикер.
 */
export function isWebSearchBuiltIntoLlm(llm: { provider: string } | undefined): boolean {
  return llm?.provider === "Perplexity";
}

export type MultiResponsePair = {
  id: string;
  llmId: string;
  webId: string;
  label: string;
};

type MultiResponseModel = {
  id: string;
  provider: string;
  model: string;
  active: boolean;
  includeInMulti: boolean;
};

/** Пары для мультиответа: LLM + совместимый web search и (кроме Perplexity) LLM без поиска. */
export function buildMultiResponsePairs(
  llmModels: MultiResponseModel[],
  webSearchModels: MultiResponseModel[],
): MultiResponsePair[] {
  const llmSelected = llmModels.filter(
    (m) => m.provider && m.model && m.active && m.includeInMulti,
  );
  const webSelected = webSearchModels.filter(
    (m) => m.provider && m.model && m.active && m.includeInMulti,
  );
  const pairs: MultiResponsePair[] = [];

  if (webSelected.length === 0) {
    return llmSelected.map((llm) => ({
      id: `${llm.id}|none`,
      llmId: llm.id,
      webId: "",
      label: `${llm.provider}/${llm.model}`,
    }));
  }

  for (const llm of llmSelected) {
    const builtInWeb = isWebSearchBuiltIntoLlm(llm);

    if (!builtInWeb) {
      pairs.push({
        id: `${llm.id}|none`,
        llmId: llm.id,
        webId: "",
        label: `${llm.provider}/${llm.model}`,
      });
    }

    for (const web of webSelected) {
      if (!isWebSearchVisibleForLlm(web, llm)) continue;
      pairs.push({
        id: `${llm.id}|${web.id}`,
        llmId: llm.id,
        webId: web.id,
        label: `${llm.provider}/${llm.model} + ${formatWebSearchComposerLabel(web.provider, web.model)}`,
      });
    }

    // Perplexity sonar: встроенный поиск, отдельный вариант «+ нет» не нужен.
    if (builtInWeb) {
      pairs.push({
        id: `${llm.id}|none`,
        llmId: llm.id,
        webId: "",
        label: `${llm.provider}/${llm.model}`,
      });
    }
  }

  return pairs;
}

export const VARIANT_TAILS = [
  "Фокус: структурно и практично.",
  "Фокус: более разговорный тон.",
  "Фокус: кратко, без потери сути.",
  "Фокус: акцент на метриках и выводах.",
];
