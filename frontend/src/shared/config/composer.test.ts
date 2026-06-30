import { describe, expect, it } from "vitest";

import { buildMultiResponsePairs } from "./composer";

const deepseek = {
  id: "llm-ds",
  provider: "DeepSeek",
  model: "deepseek-chat",
  active: true,
  includeInMulti: true,
};

const openai = {
  id: "llm-oai",
  provider: "OpenAI",
  model: "gpt-4o",
  active: true,
  includeInMulti: true,
};

const perplexity = {
  id: "llm-px",
  provider: "Perplexity",
  model: "sonar",
  active: true,
  includeInMulti: true,
};

const searchApi = {
  id: "web-px",
  provider: "Perplexity",
  model: "search-api",
  active: true,
  includeInMulti: true,
};

const openAiWeb = {
  id: "web-oai",
  provider: "OpenAI",
  model: "responses-api-web-search",
  active: true,
  includeInMulti: true,
};

describe("buildMultiResponsePairs", () => {
  it("adds plain LLM variant alongside web search for non-Perplexity models", () => {
    const pairs = buildMultiResponsePairs([deepseek], [searchApi]);

    expect(pairs).toEqual([
      {
        id: "llm-ds|none",
        llmId: "llm-ds",
        webId: "",
        label: "DeepSeek/deepseek-chat",
      },
      {
        id: "llm-ds|web-px",
        llmId: "llm-ds",
        webId: "web-px",
        label: "DeepSeek/deepseek-chat + Perplexity / search-api",
      },
    ]);
  });

  it("keeps a single Perplexity variant without extra + none when web models exist", () => {
    const pairs = buildMultiResponsePairs([perplexity], [searchApi]);

    expect(pairs).toEqual([
      {
        id: "llm-px|none",
        llmId: "llm-px",
        webId: "",
        label: "Perplexity/sonar",
      },
    ]);
  });

  it("pairs search-api with other LLMs and skips incompatible web models", () => {
    const pairs = buildMultiResponsePairs([deepseek, openai, perplexity], [searchApi, openAiWeb]);

    expect(pairs.map((pair) => pair.id)).toEqual([
      "llm-ds|none",
      "llm-ds|web-px",
      "llm-oai|none",
      "llm-oai|web-px",
      "llm-oai|web-oai",
      "llm-px|none",
    ]);
  });

  it("returns only llm|none pairs when no web models are selected for multi", () => {
    const pairs = buildMultiResponsePairs([deepseek, perplexity], []);

    expect(pairs).toEqual([
      {
        id: "llm-ds|none",
        llmId: "llm-ds",
        webId: "",
        label: "DeepSeek/deepseek-chat",
      },
      {
        id: "llm-px|none",
        llmId: "llm-px",
        webId: "",
        label: "Perplexity/sonar",
      },
    ]);
  });
});
