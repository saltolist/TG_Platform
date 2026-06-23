"use client";

import { useCallback, useEffect } from "react";
import {
  normalizeAiProfileConfig,
  normalizeExclusiveModels,
  snapshotAiConfig,
  updateExclusiveModel,
} from "@/shared/lib/profile/aiModelsSnapshot";
import { reportMutationError, showToast } from "@/shared/ui/toast";
import { restoreAiConfigFromSnapshot } from "@/shared/lib/profileDiscard";
import { buildMultiResponsePairs } from "@/shared/config/composer";
import { randomId } from "@/shared/lib/randomId";
import {
  domainActions,
  selectAiProfileConfig,
  selectModelSettingsSavedSnapshot,
  useDomainDispatch,
  useDomainSelector,
  useUi,
} from "@/app/model/store";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { useUpdateAiProfile } from "@/entities/channel";
import type { AiProfileConfig, LlmModel } from "@/shared/types";

export function useAiModelsBlock() {
  const cfg = useDomainSelector(selectAiProfileConfig);
  const modelSettingsSavedSnapshot = useDomainSelector(selectModelSettingsSavedSnapshot);
  const dispatch = useDomainDispatch();
  const { setDirty } = useUi();
  const updateAiProfile = useUpdateAiProfile();

  const update = (next: AiProfileConfig) => dispatch(domainActions.updateAiConfig(next));

  const multiResponsePairs = buildMultiResponsePairs(cfg.llmModels, cfg.webSearchModels);
  const pairCount = multiResponsePairs.length;
  const multiEligible = pairCount >= 2;

  const currentSnapshot = snapshotAiConfig(cfg);
  const dirty = currentSnapshot !== modelSettingsSavedSnapshot;

  const save = useCallback(async () => {
    const state = useProfileDraftStore.getState();
    if (!state.hydrated) return;

    const nextCfg = normalizeAiProfileConfig(state.aiProfileConfig);
    const snapshot = snapshotAiConfig(nextCfg);
    if (snapshot === state.modelSettingsSavedSnapshot) return;

    const previousSnapshot = state.modelSettingsSavedSnapshot;
    state.applyPatch({ modelSettingsSavedSnapshot: snapshot });

    try {
      const saved = await updateAiProfile.mutateAsync(nextCfg);
      const savedSnapshot = snapshotAiConfig(normalizeAiProfileConfig(saved));
      state.applyPatch({ modelSettingsSavedSnapshot: savedSnapshot });
      dispatch(domainActions.updateAiConfig(normalizeAiProfileConfig(saved)));
      showToast({ message: "Настройки ИИ-движка сохранены", variant: "info" });
    } catch (error) {
      state.applyPatch({ modelSettingsSavedSnapshot: previousSnapshot });
      reportMutationError(error, "Не удалось сохранить настройки ИИ");
    }
  }, [dispatch, updateAiProfile]);

  const cancel = useCallback(() => {
    if (!dirty) return;
    const restored = restoreAiConfigFromSnapshot(cfg, modelSettingsSavedSnapshot);
    dispatch(domainActions.updateAiConfig(restored));
  }, [cfg, dirty, dispatch, modelSettingsSavedSnapshot]);

  useEffect(() => {
    setDirty("profile-ai", dirty);
  }, [dirty, setDirty]);

  useEffect(() => {
    return () => setDirty("profile-ai", false);
  }, [setDirty]);

  const setLlms = (llmModels: LlmModel[]) => update({ ...cfg, llmModels });
  const setWebs = (webSearchModels: LlmModel[]) => update({ ...cfg, webSearchModels });
  const setVisionModels = (visionModels: LlmModel[]) => update({ ...cfg, visionModels });
  const setImageGenerationModels = (imageGenerationModels: LlmModel[]) =>
    update({ ...cfg, imageGenerationModels });
  const setOrchestrators = (orchestratorModels: LlmModel[]) =>
    update({ ...cfg, orchestratorModels: normalizeExclusiveModels(orchestratorModels) });
  const setWebReasoners = (webReasonerModels: LlmModel[]) =>
    update({ ...cfg, webReasonerModels: normalizeExclusiveModels(webReasonerModels) });
  const setRagReasoners = (ragReasonerModels: LlmModel[]) =>
    update({ ...cfg, ragReasonerModels: normalizeExclusiveModels(ragReasonerModels) });

  const addLlm = () =>
    setLlms([
      ...cfg.llmModels,
      { id: randomId(), provider: "", model: "", apiKey: "", active: true, includeInMulti: false },
    ]);
  const addWeb = () =>
    setWebs([
      ...cfg.webSearchModels,
      { id: randomId(), provider: "", model: "", apiKey: "", active: true, includeInMulti: false },
    ]);
  const addVision = () =>
    setVisionModels([
      ...cfg.visionModels,
      { id: randomId(), provider: "", model: "", apiKey: "", active: true, includeInMulti: false },
    ]);
  const addImageGeneration = () =>
    setImageGenerationModels([
      ...cfg.imageGenerationModels,
      {
        id: randomId(),
        provider: "",
        model: "",
        apiKey: "",
        active: true,
        includeInMulti: false,
      },
    ]);
  const addOrchestrator = () =>
    setOrchestrators([
      ...cfg.orchestratorModels,
      { id: randomId(), provider: "", model: "", apiKey: "", active: false, includeInMulti: false },
    ]);
  const addWebReasoner = () =>
    setWebReasoners([
      ...cfg.webReasonerModels,
      { id: randomId(), provider: "", model: "", apiKey: "", active: false, includeInMulti: false },
    ]);
  const addRagReasoner = () =>
    setRagReasoners([
      ...cfg.ragReasonerModels,
      { id: randomId(), provider: "", model: "", apiKey: "", active: false, includeInMulti: false },
    ]);

  return {
    cfg,
    dirty,
    multiEligible,
    multiResponsePairs,
    update,
    save,
    cancel,
    setLlms,
    setWebs,
    setVisionModels,
    setImageGenerationModels,
    setOrchestrators,
    setWebReasoners,
    setRagReasoners,
    addLlm,
    addWeb,
    addVision,
    addImageGeneration,
    addOrchestrator,
    addWebReasoner,
    addRagReasoner,
    updateExclusiveModel,
  };
}
