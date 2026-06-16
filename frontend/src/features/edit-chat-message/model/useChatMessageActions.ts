"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { patchGlobalChatHistory } from "@/entities/chat/lib/patchGlobalChatHistory";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { patchPostChatHistory } from "@/entities/post/lib/patchPostChatHistory";
import type { ChatMessageCtx } from "@/entities/message";
import {
  applyOmnichannelUserMessageSave,
  applyUserMessageSave,
  mapMessageAtPath,
  removeMessageAtPath,
  setActiveUserBranch,
} from "@/shared/lib/chatPaths";
import { isOmnichannelChatId } from "@/shared/lib/omnichannel";
import type { ChatMessage } from "@/shared/types";

export function useChatMessageActions() {
  const queryClient = useQueryClient();
  const { chats, posts } = useRepositories();

  const saveUserMessage = useCallback(
    (ctx: ChatMessageCtx, path: number[], text: string) => {
      if (ctx.scope === "gchat") {
        const apply = isOmnichannelChatId(ctx.entityId)
          ? applyOmnichannelUserMessageSave
          : applyUserMessageSave;
        void patchGlobalChatHistory(queryClient, chats, ctx.entityId, (history) =>
          apply(history, path, text),
        );
        return;
      }
      void patchPostChatHistory(queryClient, posts, ctx.postId, ctx.entityId, (history) =>
        applyUserMessageSave(history, path, text),
      );
    },
    [chats, posts, queryClient],
  );

  const setUserBranch = useCallback(
    (ctx: ChatMessageCtx, path: number[], branchIdx: number) => {
      const applyBranch = (history: ChatMessage[]) =>
        setActiveUserBranch(history, path, branchIdx);

      if (ctx.scope === "gchat") {
        void patchGlobalChatHistory(queryClient, chats, ctx.entityId, applyBranch);
        return;
      }
      void patchPostChatHistory(queryClient, posts, ctx.postId, ctx.entityId, applyBranch);
    },
    [chats, posts, queryClient],
  );

  const setAiVariant = useCallback(
    (ctx: ChatMessageCtx, path: number[], variantIdx: number) => {
      const applyVariant = (history: ChatMessage[]) =>
        mapMessageAtPath(history, path, (m) => ({ ...m, selectedVariant: variantIdx }));

      if (ctx.scope === "gchat") {
        void patchGlobalChatHistory(queryClient, chats, ctx.entityId, applyVariant);
        return;
      }
      void patchPostChatHistory(queryClient, posts, ctx.postId, ctx.entityId, applyVariant);
    },
    [chats, posts, queryClient],
  );

  const deleteMessage = useCallback(
    (ctx: ChatMessageCtx, path: number[]) => {
      if (ctx.scope === "gchat") {
        void patchGlobalChatHistory(queryClient, chats, ctx.entityId, (history) =>
          removeMessageAtPath(history, path),
        );
        return;
      }
      void patchPostChatHistory(queryClient, posts, ctx.postId, ctx.entityId, (history) =>
        removeMessageAtPath(history, path),
      );
    },
    [chats, posts, queryClient],
  );

  return { saveUserMessage, setUserBranch, setAiVariant, deleteMessage };
}
