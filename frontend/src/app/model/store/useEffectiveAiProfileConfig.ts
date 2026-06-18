"use client";

import { useMemo } from "react";

import { selectAiProfileConfig, useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { useAiProfile } from "@/entities/channel";
import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import type { AiProfileConfig } from "@/shared/types";

/** Draft AI profile, falling back to React Query while the draft store is still empty. */
export function useEffectiveAiProfileConfig(): AiProfileConfig {
  const draft = useProfileDraftStore(selectAiProfileConfig);
  const { data: aiFromQuery } = useAiProfile();

  return useMemo(() => {
    if (draft.llmModels.length > 0) return draft;
    if (!aiFromQuery) return draft;
    return normalizeAiProfileConfig(aiFromQuery);
  }, [aiFromQuery, draft]);
}
