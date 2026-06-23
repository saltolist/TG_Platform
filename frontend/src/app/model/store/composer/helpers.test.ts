import { describe, expect, it } from "vitest";

import {
  applyStreamingAiText,
  applyStreamingAiVariantText,
  buildAiReplyMessage,
  completeAssistantReply,
  EMPTY_AI_REPLY_FALLBACK,
  getChatSendValidationMessage,
  getLlmSendValidationMessage,
  getOrchestratorSendValidationMessage,
  resolveLlmTarget,
} from "@/app/model/store/composer/helpers";
import { initialAiProfileConfig } from "@/shared/data/seed-data";
import { buildMultiResponsePairs } from "@/shared/config/composer";
import type { AiProfileConfig } from "@/shared/types";

function multiCfg(overrides?: Partial<AiProfileConfig>): AiProfileConfig {
  return {
    ...initialAiProfileConfig,
    multiResponseEnabled: true,
    llmModels: initialAiProfileConfig.llmModels.map((m) =>
      m.id === "llm-2" ? { ...m, includeInMulti: true } : m,
    ),
    ...overrides,
  };
}

describe("completeAssistantReply", () => {
  it("returns fallback when stream resolves empty", async () => {
    const messages: string[] = [];
    const text = await completeAssistantReply(async () => "", (message) => messages.push(message));
    expect(text).toBe(EMPTY_AI_REPLY_FALLBACK);
    expect(messages).toEqual([EMPTY_AI_REPLY_FALLBACK]);
  });

  it("returns stream text on success", async () => {
    const text = await completeAssistantReply(async () => "Ответ");
    expect(text).toBe("Ответ");
  });
});

describe("resolveLlmTarget", () => {
  it("returns provider, model and apiKey for selected llm", () => {
    const cfg = multiCfg({
      llmModels: [
        {
          id: "ds-1",
          provider: "DeepSeek",
          model: "deepseek-chat",
          apiKey: "sk-test",
          active: true,
          includeInMulti: false,
        },
      ],
    });
    expect(resolveLlmTarget(cfg, "ds-1")).toEqual({
      llmId: "ds-1",
      provider: "DeepSeek",
      model: "deepseek-chat",
      apiKey: "sk-test",
    });
  });

  it("omits masked apiKey from outbound target", () => {
    const cfg = multiCfg({
      llmModels: [
        {
          id: "ds-1",
          provider: "DeepSeek",
          model: "deepseek-chat",
          apiKey: "sk-**********key",
          active: true,
          includeInMulti: false,
        },
      ],
    });
    expect(resolveLlmTarget(cfg, "ds-1")).toEqual({
      llmId: "ds-1",
      provider: "DeepSeek",
      model: "deepseek-chat",
      apiKey: undefined,
    });
  });
});

describe("buildAiReplyMessage", () => {
  it("builds multi-variant reply when multiResponseEnabled", () => {
    const cfg = multiCfg();
    const reply = buildAiReplyMessage(cfg, "Ответ", "gchat", { llmId: "llm-1", webId: "web-1" });

    expect(reply.role).toBe("ai");
    expect(reply.mode).toBe("multi");
    expect(reply.variants?.length).toBeGreaterThanOrEqual(2);
    expect(reply.selectedVariant).toBe(0);
    expect(reply.variants?.[0]?.text).toBe("Ответ");
    expect(reply.variants?.[0]?.text).not.toContain("Фокус:");
  });

  it("builds multi-variant reply with per-variant texts", () => {
    const cfg = multiCfg();
    const pairs = buildMultiResponsePairs(cfg.llmModels, cfg.webSearchModels);
    const variantTexts = Object.fromEntries(
      pairs.map((pair, idx) => [pair.id, idx === 0 ? "Ошибка ключа" : "Нормальный ответ"]),
    );
    const reply = buildAiReplyMessage(
      cfg,
      "",
      "gchat",
      { llmId: "llm-1", webId: "web-1" },
      variantTexts,
    );

    expect(reply.variants?.[0]?.text).toBe("Ошибка ключа");
    expect(reply.variants?.[1]?.text).toBe("Нормальный ответ");
  });

  it("applyStreamingAiVariantText updates only one variant", () => {
    const message = buildAiReplyMessage(multiCfg(), "", "gchat", { llmId: "llm-1", webId: "" });
    const updated = applyStreamingAiVariantText(message, message.variants![0]!.key, "Часть 1");

    expect(updated.variants?.[0]?.text).toBe("Часть 1");
    expect(updated.variants?.[1]?.text).toBe("");
  });

  it("builds single reply when multiResponseEnabled is off", () => {
    const cfg = { ...initialAiProfileConfig, multiResponseEnabled: false };
    const reply = buildAiReplyMessage(cfg, "Ответ", "gchat", { llmId: "llm-1", webId: "web-1" });

    expect(reply.mode).toBe("single");
    expect(reply.text).toBe("Ответ");
    expect(reply.llmLabel).toContain("OpenAI");
    expect(reply.variants).toBeUndefined();
  });
});

describe("chat send validation", () => {
  it("asks to add LLM when none configured", () => {
    const cfg = { ...initialAiProfileConfig, llmModels: [], orchestratorModels: [] };
    expect(getLlmSendValidationMessage(cfg, "gchat", "")).toBe("Добавьте LLM модель.");
  });

  it("asks to select LLM when nothing is chosen in composer", () => {
    const cfg = {
      ...initialAiProfileConfig,
      multiResponseEnabled: false,
      llmModels: [
        {
          id: "llm-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "",
          active: true,
          includeInMulti: false,
        },
      ],
    };
    expect(getLlmSendValidationMessage(cfg, "gchat", "")).toBe("Выберите LLM модель.");
  });

  it("asks to activate selected LLM when it is configured but inactive", () => {
    const cfg = {
      ...initialAiProfileConfig,
      multiResponseEnabled: false,
      llmModels: [
        {
          id: "llm-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "",
          active: false,
          includeInMulti: false,
        },
      ],
    };
    expect(getLlmSendValidationMessage(cfg, "gchat", "llm-1")).toBe("Активируйте LLM модель.");
  });

  it("passes when selected LLM in composer is active", () => {
    const cfg = {
      ...initialAiProfileConfig,
      multiResponseEnabled: false,
      llmModels: [
        {
          id: "llm-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "",
          active: true,
          includeInMulti: false,
        },
      ],
    };
    expect(getLlmSendValidationMessage(cfg, "gchat", "llm-1")).toBeNull();
  });

  it("asks to add orchestrator when list is empty", () => {
    const cfg = { ...initialAiProfileConfig, orchestratorModels: [] };
    expect(getOrchestratorSendValidationMessage(cfg)).toBe("Добавьте модель оркестратора.");
  });

  it("asks to activate orchestrator when configured but inactive", () => {
    const cfg = {
      ...initialAiProfileConfig,
      orchestratorModels: [
        {
          id: "orchestrator-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "",
          active: false,
          includeInMulti: false,
        },
      ],
    };
    expect(getOrchestratorSendValidationMessage(cfg)).toBe("Активируйте модель оркестратора.");
  });

  it("checks only LLM and orchestrator, not web or rag reasoners", () => {
    const cfg = {
      ...initialAiProfileConfig,
      orchestratorModels: [],
      webReasonerModels: [],
      ragReasonerModels: [],
    };
    expect(getChatSendValidationMessage(cfg, "gchat", "llm-1")).toBe("Добавьте модель оркестратора.");
  });

  it("skips orchestrator in presentation mode when LLM is ready", () => {
    const cfg = {
      ...initialAiProfileConfig,
      orchestratorModels: [],
      multiResponseEnabled: false,
      llmModels: [
        {
          id: "llm-1",
          provider: "OpenAI",
          model: "gpt-4o",
          apiKey: "",
          active: true,
          includeInMulti: false,
        },
      ],
    };
    expect(
      getChatSendValidationMessage(cfg, "gchat", "llm-1", { requireOrchestrator: false }),
    ).toBeNull();
  });

  it("prioritizes LLM message before orchestrator", () => {
    const cfg = {
      ...initialAiProfileConfig,
      llmModels: [],
      orchestratorModels: [],
    };
    expect(getChatSendValidationMessage(cfg, "gchat", "")).toBe("Добавьте LLM модель.");
  });
});
