"use client";

import { useEffect, useRef } from "react";

import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import {
  useAiProfile,
  useChannelProfile,
  useTelegramProfile,
} from "@/entities/channel";

/** Loads React Query profile data into the local draft store after account switch. */
export function ProfileHydrator() {
  const accountId = useQueryAccountScope();
  const { data: channel } = useChannelProfile();
  const { data: ai } = useAiProfile();
  const { data: telegram } = useTelegramProfile();
  const hydrateFromServer = useProfileDraftStore((s) => s.hydrateFromServer);
  const lastHydratedAccountRef = useRef<string | null>(null);

  useEffect(() => {
    lastHydratedAccountRef.current = null;
  }, [accountId]);

  useEffect(() => {
    if (!channel || !ai || !telegram) return;
    if (lastHydratedAccountRef.current === accountId) return;
    hydrateFromServer(channel, ai, telegram);
    lastHydratedAccountRef.current = accountId;
  }, [accountId, ai, channel, hydrateFromServer, telegram]);

  return null;
}
