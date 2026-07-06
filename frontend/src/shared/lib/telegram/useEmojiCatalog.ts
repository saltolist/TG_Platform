"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

import { useRepositories } from "@/app/providers/RepositoryProvider";
import { ApiError } from "@/shared/api/httpClient";

export const EMOJI_CATALOG_QUERY_KEY = ["telegram-emoji-catalog"] as const;
const EMOJI_CATALOG_STALE_MS = 5 * 60 * 1000;

export function usePrefetchEmojiCatalog() {
  const { telegramEmoji } = useRepositories();
  const queryClient = useQueryClient();

  return useCallback(() => {
    void queryClient.prefetchQuery({
      queryKey: EMOJI_CATALOG_QUERY_KEY,
      queryFn: () => telegramEmoji.catalog(),
      staleTime: EMOJI_CATALOG_STALE_MS,
    });
  }, [queryClient, telegramEmoji]);
}

/** Warm catalog in the background while the composer is on screen. */
export function useWarmEmojiCatalog() {
  const prefetch = usePrefetchEmojiCatalog();
  useEffect(() => {
    const timer = window.setTimeout(prefetch, 400);
    return () => window.clearTimeout(timer);
  }, [prefetch]);
}

export function useEmojiCatalog(enabled = true) {
  const { telegramEmoji } = useRepositories();
  return useQuery({
    queryKey: EMOJI_CATALOG_QUERY_KEY,
    queryFn: () => telegramEmoji.catalog(),
    enabled,
    staleTime: EMOJI_CATALOG_STALE_MS,
    retry: (failureCount, error) => {
      if (failureCount >= 2) return false;
      if (error instanceof ApiError && error.status >= 500) {
        return true;
      }
      return failureCount < 1;
    },
    retryDelay: (attempt) => Math.min(4000 * (attempt + 1), 12000),
  });
}
