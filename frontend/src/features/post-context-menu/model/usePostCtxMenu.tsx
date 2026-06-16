"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";

import SchedulePickerModal from "@/features/schedule-post/ui/SchedulePickerModal";
import {
  buildPostCtxMenuItems,
  getDefaultScheduleDate,
} from "@/features/post-context-menu/lib/buildItems";
import { useDeletePost, useUpdatePost } from "@/entities/post";
import { parsePostDateTime, postTitle } from "@/shared/lib/helpers";
import { routes } from "@/shared/lib/routes";
import { confirmDialog } from "@/shared/ui/dialog";
import type { CtxMenuItem } from "@/shared/ui/context-menu";
import type { Post } from "@/shared/types";

export type PostCtxMenuResult = {
  items: CtxMenuItem[];
  modal: ReactNode;
};

type Actions = {
  onNewChat: () => void;
  onNewNote: () => void;
};

export function usePostCtxMenuItems(
  post: Post | null | undefined,
  actions: Actions,
): PostCtxMenuResult {
  const router = useRouter();
  const updatePost = useUpdatePost();
  const deletePost = useDeletePost();
  const [isScheduleOpen, setIsScheduleOpen] = useState(false);
  const [scheduleInitialDate, setScheduleInitialDate] = useState<Date>(() => getDefaultScheduleDate());

  const closeSchedule = useCallback(() => {
    setIsScheduleOpen(false);
  }, []);

  const openScheduleModal = useCallback((initial?: Date) => {
    setScheduleInitialDate(initial ?? getDefaultScheduleDate());
    setIsScheduleOpen(true);
  }, []);

  const confirmSchedule = useCallback(
    (value: string) => {
      if (!post) return;
      const selected = new Date(value);
      if (Number.isNaN(selected.getTime())) return;
      void updatePost.mutateAsync({
        id: post.id,
        patch: {
          status: "scheduled",
          date: selected.toISOString(),
        },
      });
      setIsScheduleOpen(false);
    },
    [post, updatePost],
  );

  useEffect(() => {
    if (!isScheduleOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsScheduleOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isScheduleOpen]);

  const items = useMemo(() => {
    if (!post) return [];

    return buildPostCtxMenuItems(post, {
      onNewChat: actions.onNewChat,
      onNewNote: actions.onNewNote,
      onPublish: () => {
        void updatePost.mutateAsync({
          id: post.id,
          patch: {
            status: "published",
            date: new Date().toISOString(),
            metrics: { views: "0", reposts: 0, reactions: [] },
          },
        });
      },
      onSchedule: () => openScheduleModal(),
      onReschedule: () =>
        openScheduleModal(parsePostDateTime(post.date) ?? getDefaultScheduleDate()),
      onCancelPublish: () => {
        void updatePost.mutateAsync({
          id: post.id,
          patch: { status: "draft", created: new Date().toISOString() },
        });
      },
      onDelete: () => {
        void (async () => {
          const ok = await confirmDialog({
            message: `Удалить пост «${postTitle(post)}»?`,
            confirmLabel: "Удалить",
            destructive: true,
          });
          if (!ok) return;
          void deletePost.mutateAsync(post.id).then(() => {
            router.replace(routes.feed());
          });
        })();
      },
    });
  }, [actions.onNewChat, actions.onNewNote, deletePost, openScheduleModal, post, router, updatePost]);

  const modal =
    isScheduleOpen && typeof document !== "undefined"
      ? createPortal(
          <SchedulePickerModal
            key={scheduleInitialDate.getTime()}
            initialDate={scheduleInitialDate}
            plannedDate={post?.status === "scheduled" ? parsePostDateTime(post.date) : null}
            onClose={closeSchedule}
            onConfirm={confirmSchedule}
          />,
          document.body,
        )
      : null;

  return { items, modal };
}
