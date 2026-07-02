"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { applyPostUpdate } from "@/entities/post/model/usePosts";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";

const POLL_INTERVAL_MS = 5_000;

/**
 * While a post page (or its comments tab) is open, periodically refetch that
 * post from our DB. Live-sync already writes inbound TG comments in batches;
 * this keeps the UI fresh without hitting Telegram on every tick.
 */
export function usePollOpenPost(postId: string | null | undefined, enabled: boolean) {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const authEnabled = useAuthenticatedQueryEnabled();

  useEffect(() => {
    if (!enabled || !authEnabled || !postId) return;

    let cancelled = false;

    const tick = async () => {
      if (document.hidden) return;
      try {
        const fresh = await posts.get(postId);
        if (cancelled) return;
        applyPostUpdate(queryClient, accountId, fresh);
      } catch {
        // Transient errors — keep polling.
      }
    };

    const onFocus = () => {
      void tick();
    };

    void tick();
    const intervalId = window.setInterval(() => {
      void tick();
    }, POLL_INTERVAL_MS);
    window.addEventListener("focus", onFocus);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", onFocus);
    };
  }, [accountId, authEnabled, enabled, postId, posts, queryClient]);
}
