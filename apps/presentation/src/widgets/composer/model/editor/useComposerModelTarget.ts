"use client";

import { useEffect, useMemo } from "react";

import { useComposer } from "@/app/model/store/composer-store";
import { selectAiProfileConfig, useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { useComposerTargetStore } from "@/app/model/store/composer-target-store";
import { isWebSearchVisibleForLlm } from "@/shared/config/composer";
import type { ComposerScope } from "@/shared/types";

export function useComposerModelTarget(scope: ComposerScope) {
  const cfg = useProfileDraftStore(selectAiProfileConfig);
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
    setLlmId(scope, llmOptions[0]!.id);
  }, [llmOptions, scope, setLlmId, target.llmId]);

  const webOptionsAll = useMemo(
    () => cfg.webSearchModels.filter((m) => m.provider && m.model && m.active),
    [cfg.webSearchModels],
  );
  const selectedLlm = llmOptions.find((m) => m.id === target.llmId);
  const webOptions = webOptionsAll.filter((m) => isWebSearchVisibleForLlm(m, selectedLlm));

  useEffect(() => {
    const webIdValid = target.webId && webOptions.some((m) => m.id === target.webId);
    if (webIdValid || webOptions.length === 0) return;
    setWebId(scope, webOptions[0]!.id);
  }, [scope, setWebId, target.webId, webOptions]);

  const webValue =
    target.webId && webOptions.some((m) => m.id === target.webId) ? target.webId : "";

  return useMemo(
    () => ({
      llmOptions,
      webOptions,
      llmId: target.llmId,
      webId: webValue,
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
      webOptions,
      webValue,
    ],
  );
}
