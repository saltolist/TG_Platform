"use client";

import { useEffect } from "react";

import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import {
  useAiProfile,
  useChannelProfile,
  useTelegramProfile,
} from "@/entities/channel";
import { normalizeAiProfileConfig } from "@/shared/lib/profile/aiModelsSnapshot";
import {
  normalizeChannelProfileConfig,
  normalizeTelegramProfileConfig,
} from "@/shared/lib/profile/normalizeProfileConfig";

/** Loads React Query profile data into the local draft store after account switch. */
export function ProfileHydrator() {
  const accountId = useQueryAccountScope();
  const { data: channel } = useChannelProfile();
  const { data: ai } = useAiProfile();
  const { data: telegram } = useTelegramProfile();
  const hydrateFromServer = useProfileDraftStore((s) => s.hydrateFromServer);

  useEffect(() => {
    if (!ai) return;
    hydrateFromServer(
      normalizeChannelProfileConfig(channel),
      normalizeAiProfileConfig(ai),
      normalizeTelegramProfileConfig(telegram),
    );
  }, [accountId, ai, channel, hydrateFromServer, telegram]);

  return null;
}
