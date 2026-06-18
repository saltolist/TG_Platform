"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { useComposer } from "@/app/model/store/composer-store";
import { usePostNavigationStore } from "@/app/model/store/post-navigation-store";
import { resolvePostChatId } from "@/entities/post/lib/resolvePostChatId";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { guardedPush } from "@/widgets/app-shell/lib/guardedNavigation";
import { parseAppPath, parseChatSearchParam, parseGChatSearchParam } from "@/shared/lib/routes";

export function ComposerNavBridge() {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const { registerNavBridge } = useComposer();

  useEffect(() => {
    return registerNavBridge({
      goToHref: (href, opts) => {
        void guardedPush(router, href, { replace: opts?.replace });
        return true;
      },
      getCurrentGChatId: () => {
        const parsed = parseAppPath(pathname);
        return parsed.gchatId ?? parseGChatSearchParam(searchParams.get("id"));
      },
      getCurrentPostId: () => {
        const parsed = parseAppPath(pathname);
        return parsed.postId;
      },
      getCurrentPostChatId: () => {
        const parsed = parseAppPath(pathname);
        if (parsed.postId == null) return null;

        const nav = usePostNavigationStore.getState();
        if (nav.isPendingNewPostChat(parsed.postId)) return null;

        const storeChatId = nav.getCurrentPostChatId(parsed.postId);
        const fromUrl = parseChatSearchParam(searchParams.get("chat"));
        const candidate = storeChatId ?? fromUrl;
        return resolvePostChatId(queryClient, parsed.postId, candidate);
      },
      setCurrentPostChatId: (chatId: string) => {
        const parsed = parseAppPath(pathname);
        if (parsed.postId == null) return;
        const nav = usePostNavigationStore.getState();
        nav.setPendingNewPostChat(parsed.postId, false);
        nav.setMode(parsed.postId, "chat", chatId);
      },
    });
  }, [accountId, pathname, queryClient, registerNavBridge, router, searchParams]);

  return null;
}
