"use client";

import { isTelegramChannelConnected } from "@/shared/lib/channel/isTelegramChannelConnected";
import { isQueryBootstrapping } from "@/shared/lib/query/isQueryBootstrapping";
import { useTelegramProfile } from "./useProfile";

export function useChannelConnected() {
  const { data: telegram, isLoading } = useTelegramProfile();

  return {
    telegram,
    isLoading: isQueryBootstrapping(isLoading, telegram),
    isConnected: isTelegramChannelConnected(telegram),
  };
}
