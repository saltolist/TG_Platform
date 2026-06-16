"use client";

import { useCallback } from "react";

import { useRenameGlobalChat } from "@/entities/chat";
import { useRenameLocalChat } from "@/entities/post";

type GlobalTarget = { scope: "global"; chatId: string };
type LocalTarget = { scope: "local"; postId: string; chatId: string };

export function useRenameChat() {
  const renameGlobalChat = useRenameGlobalChat();
  const renameLocalChat = useRenameLocalChat();

  return useCallback(
    (target: GlobalTarget | LocalTarget, title: string) => {
      const next = window.prompt("Новое название чата", title);
      if (next == null) return;
      const t = next.trim();
      if (!t) return;
      if (target.scope === "global") {
        void renameGlobalChat.mutateAsync({ chatId: target.chatId, title: t });
      } else {
        void renameLocalChat(target.postId, target.chatId, t);
      }
    },
    [renameGlobalChat, renameLocalChat],
  );
}
