"use client";

import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { useCallback } from "react";

import { routes } from "@/shared/lib/routes";
import type { ActiveNote, GlobalNote, NoteFromScreen, ScreenId } from "@/shared/types";
import type { RecentNoteRow, RecentRow } from "@/widgets/sidebar/model/types";

type Params = {
  router: AppRouterInstance;
  screen: ScreenId;
  gchatIdFromUrl: string | null;
  postChatIdFromUrl: string | null;
  routePostId: string | null;
  currentNote: ActiveNote | null;
  noteFrom: NoteFromScreen | null;
  globalNotes: GlobalNote[];
  renameGlobalChat: { mutateAsync: (args: { chatId: string; title: string }) => Promise<unknown> };
  deleteGlobalChat: { mutateAsync: (id: string) => Promise<unknown> };
  renameLocalChat: (postId: string, chatId: string, title: string) => void;
  deleteLocalChat: (postId: string, chatId: string) => void;
  upsertGlobalNote: { mutateAsync: (note: GlobalNote) => Promise<unknown> };
  updatePostNote: (postId: string, noteId: string, patch: { title: string }) => void;
  deleteGlobalNote: { mutateAsync: (id: string) => Promise<unknown> };
  deletePostNote: (postId: string, noteId: string) => void;
};

export function useSidebarRecentMutations({
  router,
  screen,
  gchatIdFromUrl,
  postChatIdFromUrl,
  routePostId,
  currentNote,
  noteFrom,
  globalNotes,
  renameGlobalChat,
  deleteGlobalChat,
  renameLocalChat,
  deleteLocalChat,
  upsertGlobalNote,
  updatePostNote,
  deleteGlobalNote,
  deletePostNote,
}: Params) {
  const renameRecentChat = useCallback(
    (row: RecentRow, title: string) => {
      if (row.kind === "global") {
        void renameGlobalChat.mutateAsync({ chatId: row.id, title });
        return;
      }
      void renameLocalChat(row.postId, row.chatId, title);
    },
    [renameGlobalChat, renameLocalChat],
  );

  const deleteRecentChat = useCallback(
    (row: RecentRow) => {
      if (row.kind === "global") {
        void deleteGlobalChat.mutateAsync(row.id);
        if (screen === "gchat" && gchatIdFromUrl === row.id) {
          router.replace(routes.chats());
        }
        return;
      }
      void deleteLocalChat(row.postId, row.chatId);
      if (
        screen === "post" &&
        routePostId === row.postId &&
        postChatIdFromUrl === row.chatId
      ) {
        router.replace(routes.post(row.postId));
      }
    },
    [
      deleteGlobalChat,
      deleteLocalChat,
      gchatIdFromUrl,
      postChatIdFromUrl,
      routePostId,
      router,
      screen,
    ],
  );

  const renameRecentNote = useCallback(
    (row: RecentNoteRow, title: string) => {
      if (row.kind === "global") {
        const note = globalNotes.find((n) => n.id === row.id);
        if (!note) return;
        void upsertGlobalNote.mutateAsync({ ...note, title });
        return;
      }
      void updatePostNote(row.postId, row.noteId, { title });
    },
    [globalNotes, updatePostNote, upsertGlobalNote],
  );

  const deleteRecentNote = useCallback(
    (row: RecentNoteRow) => {
      if (row.kind === "global") {
        void deleteGlobalNote.mutateAsync(row.id);
        const cur = currentNote;
        if (screen === "note" && cur?.isGlobal === true && cur.id === row.id) {
          router.replace(routes.notes());
        }
        return;
      }
      void deletePostNote(row.postId, row.noteId);
      const cur = currentNote;
      if (
        screen === "note" &&
        cur &&
        cur.isGlobal === false &&
        cur.postId === row.postId &&
        cur.id === row.noteId
      ) {
        router.replace(noteFrom === "post" ? routes.post(row.postId) : routes.notes());
      }
    },
    [currentNote, deleteGlobalNote, deletePostNote, noteFrom, router, screen],
  );

  return { renameRecentChat, deleteRecentChat, renameRecentNote, deleteRecentNote };
}
