"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

import { useNavigationStore } from "@/app/model/store";
import { useGlobalNotes, useUpsertGlobalNote } from "@/entities/note";
import { useChannelConnected } from "@/entities/channel";
import { usePosts, useTogglePostNoteAi } from "@/entities/post";
import { guardedPush } from "@/widgets/app-shell/lib/guardedNavigation";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import {
  buildAnyNoteItems,
  filterAnyNotes,
  filterNotesByScope,
  notesEmptyLabel,
  type AnyNote,
} from "@/shared/lib/notes/noteList";
import { isListQueryBootstrapping } from "@/shared/lib/query/isQueryBootstrapping";
import { routes } from "@/shared/lib/routes";

export function useNotesScreen() {
  const router = useRouter();
  const isMobile = useMobile760();
  const scope = useNavigationStore((s) => s.noteScope);
  const filter = useNavigationStore((s) => s.noteFilter);
  const search = useNavigationStore((s) => s.notesSearch);

  const { data: globalNotes = [], isLoading: globalLoading } = useGlobalNotes();
  const { data: posts = [], isLoading: postsLoading } = usePosts();
  const { isConnected: isChannelConnected, isLoading: isChannelLoading } = useChannelConnected();
  const upsertGlobalNote = useUpsertGlobalNote();
  const togglePostNoteAi = useTogglePostNoteAi();

  const allItems = useMemo(() => buildAnyNoteItems(globalNotes, posts), [globalNotes, posts]);
  const items = useMemo(() => filterNotesByScope(allItems, scope), [allItems, scope]);

  const filtered = useMemo(
    () => filterAnyNotes(items, { filter, searchQuery: search }),
    [filter, items, search],
  );

  const showConnectChannel =
    !isChannelLoading && !isChannelConnected && !search.trim() && allItems.length === 0;

  const openNote = useCallback(
    (n: AnyNote) => {
      const href = n.isGlobal ? routes.noteGlobal(n.id) : routes.notePost(n.postId, n.id);
      void guardedPush(router, href);
    },
    [router],
  );

  const toggleAi = useCallback(
    (n: AnyNote) => {
      if (n.isGlobal) {
        void upsertGlobalNote.mutateAsync({ ...n, ai: !n.ai });
      } else {
        void togglePostNoteAi(n.postId, n.id);
      }
    },
    [togglePostNoteAi, upsertGlobalNote],
  );

  const newGlobal = useCallback(() => {
    void guardedPush(router, routes.noteNew("notes"));
  }, [router]);

  return {
    data: {
      scope,
      filter,
      filtered,
      emptyLabel: notesEmptyLabel(scope),
      showConnectChannel,
      isLoading:
        isListQueryBootstrapping(globalLoading, globalNotes) ||
        isListQueryBootstrapping(postsLoading, posts),
    },
    ui: {
      isMobile,
    },
    actions: {
      openNote,
      toggleAi,
      newGlobal,
    },
  };
}

export type NotesScreenState = ReturnType<typeof useNotesScreen>;
