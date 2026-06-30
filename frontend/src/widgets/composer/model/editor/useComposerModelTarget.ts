"use client";

import { useEffect, useMemo } from "react";

import { useComposer } from "@/app/model/store/composer-store";
import { useEffectiveAiProfileConfig } from "@/app/model/store/useEffectiveAiProfileConfig";
import { useComposerTargetStore } from "@/app/model/store/composer-target-store";
import {
  isWebSearchBuiltIntoLlm,
  isWebSearchVisibleForLlm,
} from "@/shared/config/composer";
import type { ComposerScope } from "@/shared/types";

export function useComposerModelTarget(scope: ComposerScope) {
  const cfg = useEffectiveAiProfileConfig();
  const target = useComposerTargetStore((s) => s.targets[scope]);
  const setLlmId = useComposerTargetStore((s) => s.setLlmId);
  const setWebId = useComposerTargetStore((s) => s.setWebId);
  const { setComposerLlm, setComposerWeb } = useComposer();

  const llmOptions = useMemo(
    () => cfg.llmModels.filter((m) => m.provider && m.model && m.active),
    [cfg.llmModels],
  );

  useEffect(() => {
    if (llmOptions.length === 0) return;
    const valid = target.llmId && llmOptions.some((model) => model.id === target.llmId);
    if (valid) return;
    const defaultLlm = llmOptions.find((model) => model.active) ?? llmOptions[0]!;
    setLlmId(scope, defaultLlm.id);
  }, [llmOptions, scope, setLlmId, target.llmId]);

  const webOptionsAll = useMemo(
    () => cfg.webSearchModels.filter((m) => m.provider && m.model && m.active),
    [cfg.webSearchModels],
  );

  const selectedLlm = llmOptions.find((m) => m.id === target.llmId);

  // Когда LLM=Perplexity — поиск встроен, внешние web-модели не показываем
  const webBuiltIn = isWebSearchBuiltIntoLlm(selectedLlm);
  const webOptions = webBuiltIn
    ? []
    : webOptionsAll.filter((m) => isWebSearchVisibleForLlm(m, selectedLlm));

  // Сбрасываем webId, если текущий выбор больше не виден
  useEffect(() => {
    if (webBuiltIn) {
      // Perplexity LLM — принудительно очищаем web-выбор в сторе
      if (target.webId) setWebId(scope, "");
      return;
    }
    const webIdValid = target.webId && webOptions.some((m) => m.id === target.webId);
    if (webIdValid || webOptions.length === 0) return;
    // Для других LLM — не выбираем web-модель по умолчанию (пользователь выберет явно)
    if (target.webId) setWebId(scope, "");
  }, [scope, setWebId, target.webId, webOptions, webBuiltIn]);

  const webValue =
    !webBuiltIn && target.webId && webOptions.some((m) => m.id === target.webId)
      ? target.webId
      : "";

  return useMemo(
    () => ({
      llmOptions,
      webOptions,
      llmId: target.llmId,
      webId: webValue,
      webBuiltIn,
      isMulti: cfg.multiResponseEnabled,
      setComposerLlm,
      setComposerWeb,
    }),
    [
      cfg.multiResponseEnabled,
      llmOptions,
      setComposerLlm,
      setComposerWeb,
      target.llmId,
      webBuiltIn,
      webOptions,
      webValue,
    ],
  );
}
