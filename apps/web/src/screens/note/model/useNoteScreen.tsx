"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

import { useUiStore } from "@/app/model/store";
import { useNavigationStore } from "@/app/model/store/navigation-store";
import type { NavigationPatch } from "@/app/model/store/navigation/types";
import { usePostNavigationStore } from "@/app/model/store/post-navigation-store";
import { useDeleteGlobalNote, useUpsertGlobalNote } from "@/entities/note";
import { getCachedPost } from "@/entities/post/lib/getCachedPost";
import {
  useDeletePostNote,
  useTogglePostNoteAi,
} from "@/entities/post/model/usePostNoteMutations";
import {
  resolveScreenBackAction,
  type ScreenBackAction,
} from "@/shared/lib/hooks/useScreenBack";
import { confirmLeaveNote } from "@/shared/lib/noteLeave";
import { confirmDialog } from "@/shared/ui/dialog";
import { routes } from "@/shared/lib/routes";
import {
  MenuIconBrain,
  MenuIconBrainOff,
  MenuIconCancel,
  MenuIconTrash,
} from "@/shared/ui/icons/header-menu-icons";
import type { PageHeaderOverflowItem } from "@/widgets/page-header";
import type { ActiveNote, ScreenId } from "@/shared/types";

export function useNoteScreen(note: ActiveNote | null) {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const queryClient = useQueryClient();
  const noteFrom = useNavigationStore((s) => s.noteFrom);
  const setNav = useNavigationStore((s) => s.setNav);
  const setPostMode = usePostNavigationStore((s) => s.setMode);
  const noteDirty = useUiStore((s) => s.noteDirty);
  const setNoteDirty = useUiStore((s) => s.setNoteDirty);
  const deleteGlobalNote = useDeleteGlobalNote();
  const upsertGlobalNote = useUpsertGlobalNote();
  const deletePostNote = useDeletePostNote();
  const togglePostNoteAi = useTogglePostNoteAi();

  const backFallback: ScreenId = noteFrom === "post" ? "post" : "notes";

  const parentPost = useMemo(() => {
    if (!note || note.isGlobal) return null;
    return getCachedPost(queryClient, note.postId) ?? null;
  }, [note, queryClient]);

  const patchNote = useCallback(
    (patch: NavigationPatch) => {
      setNav(patch);
    },
    [setNav],
  );

  const navigateWithConfirm = useCallback(
    async (href: string, options?: { replace?: boolean }) => {
      if (!(await confirmLeaveNote(note, noteDirty))) return;
      setNoteDirty(false);
      if (options?.replace) router.replace(href);
      else router.push(href);
    },
    [note, noteDirty, router, setNoteDirty],
  );

  const discardNewNote = useCallback(async () => {
    if (!(await confirmLeaveNote(note, noteDirty))) return;
    setNoteDirty(false);
    if (noteFrom === "post" && note && !note.isGlobal) {
      router.replace(routes.post(note.postId));
    } else {
      router.replace(routes.notes());
    }
  }, [note, noteDirty, noteFrom, router, setNoteDirty]);

  const onBack = useCallback(async () => {
    if (!(await confirmLeaveNote(note, noteDirty))) return;
    setNoteDirty(false);
    const params =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search)
        : new URLSearchParams();
    const action: ScreenBackAction = resolveScreenBackAction(pathname, params);
    if (action.type === "back") router.back();
    else router.push(action.href);
  }, [note, noteDirty, pathname, router, setNoteDirty]);

  const setNoteAi = useCallback(
    (ai: boolean) => {
      if (!note) return;
      if (note.ai === ai) return;
      if (note.isNew) {
        patchNote({ currentNote: { ...note, ai } });
        return;
      }
      if (note.isGlobal) {
        void upsertGlobalNote.mutateAsync({ ...note, ai });
        patchNote({ currentNote: { ...note, ai } });
      } else {
        void togglePostNoteAi(note.postId, note.id);
        patchNote({ currentNote: { ...note, ai } });
      }
    },
    [note, patchNote, togglePostNoteAi, upsertGlobalNote],
  );

  const deleteNote = useCallback(async () => {
    if (!note || note.isNew) return;
    const ok = await confirmDialog({
      message: `Удалить заметку «${note.title}»?`,
      confirmLabel: "Удалить",
      destructive: true,
    });
    if (!ok) return;
    if (note.isGlobal) {
      void deleteGlobalNote.mutateAsync(note.id);
      router.replace(routes.notes());
    } else {
      void deletePostNote(note.postId, note.id);
      router.replace(routes.post(note.postId));
    }
    setNoteDirty(false);
  }, [deleteGlobalNote, deletePostNote, note, router, setNoteDirty]);

  const noteHeaderMenuItems = useMemo((): PageHeaderOverflowItem[] => {
    if (!note) return [];
    return [
      {
        label: note.ai ? "Не учитывать в ИИ" : "Учитывать в ИИ",
        icon: note.ai ? <MenuIconBrainOff /> : <MenuIconBrain />,
        onClick: () => setNoteAi(!note.ai),
      },
      {
        label: note.isNew ? "Отменить" : "Удалить заметку",
        icon: note.isNew ? <MenuIconCancel /> : <MenuIconTrash />,
        danger: !note.isNew,
        onClick: () => {
          if (note.isNew) {
            void discardNewNote();
            return;
          }
          void deleteNote();
        },
      },
    ];
  }, [deleteNote, discardNewNote, note, setNoteAi]);

  const openPost = useCallback(
    (postId: string) => {
      setPostMode(postId, "chat");
      navigateWithConfirm(routes.post(postId));
    },
    [navigateWithConfirm, setPostMode],
  );

  return {
    data: {
      backFallback,
      parentPost,
    },
    ui: {
      noteHeaderMenuItems,
    },
    actions: {
      onBack,
      navigateNotes: () => navigateWithConfirm(routes.notes()),
      navigateFeed: () => navigateWithConfirm(routes.feed()),
      openPost,
    },
  };
}

export type NoteScreenState = ReturnType<typeof useNoteScreen>;
