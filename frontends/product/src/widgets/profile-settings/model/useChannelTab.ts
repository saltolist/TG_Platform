"use client";

import { useEffect, useMemo } from "react";
import {
  domainActions,
  selectChannelProfileConfig,
  selectChannelProfileSavedSnapshot,
  useDomainActions,
  useDomainDispatch,
  useDomainSelector,
  useUi,
} from "@/app/model/store";
import { randomId } from "@/shared/lib/randomId";
import type { ChannelProfileConfig, ChannelProfileRubric } from "@/shared/types";

export function useChannelTab() {
  const cfg = useDomainSelector(selectChannelProfileConfig);
  const channelProfileSavedSnapshot = useDomainSelector(selectChannelProfileSavedSnapshot);
  const dispatch = useDomainDispatch();
  const { applyPatch } = useDomainActions();
  const { setDirty } = useUi();
  const savedCfg = useMemo(
    () => JSON.parse(channelProfileSavedSnapshot) as ChannelProfileConfig,
    [channelProfileSavedSnapshot],
  );
  const channelProfileSnapshot = useMemo(
    () => JSON.stringify({ core: cfg.core, voice: cfg.voice, rules: cfg.rules }),
    [cfg.core, cfg.voice, cfg.rules],
  );
  const savedChannelProfileSnapshot = useMemo(
    () => JSON.stringify({ core: savedCfg.core, voice: savedCfg.voice, rules: savedCfg.rules }),
    [savedCfg.core, savedCfg.voice, savedCfg.rules],
  );
  const rubricsSnapshot = useMemo(() => JSON.stringify(cfg.rubrics), [cfg.rubrics]);
  const savedRubricsSnapshot = useMemo(() => JSON.stringify(savedCfg.rubrics), [savedCfg.rubrics]);
  const channelProfileDirty = channelProfileSnapshot !== savedChannelProfileSnapshot;
  const rubricsDirty = rubricsSnapshot !== savedRubricsSnapshot;
  const dirty = channelProfileDirty || rubricsDirty;

  useEffect(() => {
    setDirty("profile-channel", dirty);
  }, [dirty, setDirty]);

  useEffect(() => {
    return () => setDirty("profile-channel", false);
  }, [setDirty]);

  const update = (next: ChannelProfileConfig) => dispatch(domainActions.updateChannelProfile(next));

  const saveChannelProfile = () => {
    if (!channelProfileDirty) return;
    applyPatch({
      channelProfileSavedSnapshot: JSON.stringify({
        ...savedCfg,
        core: cfg.core,
        voice: cfg.voice,
        rules: cfg.rules,
      }),
    });
  };

  const resetChannelProfile = () => {
    if (!channelProfileDirty) return;
    update({
      ...cfg,
      core: savedCfg.core,
      voice: savedCfg.voice,
      rules: savedCfg.rules,
    });
  };

  const saveRubrics = () => {
    if (!rubricsDirty) return;
    applyPatch({
      channelProfileSavedSnapshot: JSON.stringify({
        ...savedCfg,
        rubrics: cfg.rubrics,
      }),
    });
  };

  const resetRubrics = () => {
    if (!rubricsDirty) return;
    update({ ...cfg, rubrics: savedCfg.rubrics });
  };

  const updateGroup = <K extends keyof ChannelProfileConfig>(
    group: K,
    patch: Partial<ChannelProfileConfig[K]>,
  ) => update({ ...cfg, [group]: { ...cfg[group], ...patch } });

  const addRubric = () =>
    update({
      ...cfg,
      rubrics: [
        ...cfg.rubrics,
        {
          id: randomId(),
          title: "Новая рубрика",
          description: "",
        },
      ],
    });

  const updateRubric = (id: string, patch: Partial<ChannelProfileRubric>) =>
    update({
      ...cfg,
      rubrics: cfg.rubrics.map((rubric) => (rubric.id === id ? { ...rubric, ...patch } : rubric)),
    });

  const removeRubric = (id: string) =>
    update({ ...cfg, rubrics: cfg.rubrics.filter((rubric) => rubric.id !== id) });

  return {
    cfg,
    channelProfileDirty,
    rubricsDirty,
    updateGroup,
    saveChannelProfile,
    resetChannelProfile,
    saveRubrics,
    resetRubrics,
    addRubric,
    updateRubric,
    removeRubric,
  };
}
