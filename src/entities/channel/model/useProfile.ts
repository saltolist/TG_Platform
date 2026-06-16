"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import type {
  AiProfileConfig,
  ChannelProfileConfig,
  TelegramProfileConfig,
} from "@/shared/types";

export function useChannelProfile() {
  const { profile } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.profile.channel(accountId),
    queryFn: () => profile.getChannel(),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useUpdateChannelProfile() {
  const { profile } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (config: ChannelProfileConfig) => profile.updateChannel(config),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.profile.channel(accountId), data);
    },
  });
}

export function useAiProfile() {
  const { profile } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.profile.ai(accountId),
    queryFn: () => profile.getAi(),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useUpdateAiProfile() {
  const { profile } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (config: AiProfileConfig) => profile.updateAi(config),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.profile.ai(accountId), data);
    },
  });
}

export function useTelegramProfile() {
  const { profile } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.profile.telegram(accountId),
    queryFn: () => profile.getTelegram(),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useUpdateTelegramProfile() {
  const { profile } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (config: TelegramProfileConfig) => profile.updateTelegram(config),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.profile.telegram(accountId), data);
    },
  });
}
