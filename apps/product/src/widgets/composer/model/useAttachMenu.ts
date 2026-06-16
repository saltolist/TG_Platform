"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import type { AttachSubmenuKey } from "@/widgets/composer/ui/AttachHomeScopeMenu";
import {
  collectAttachedMedia,
  nextAttachMenuId,
} from "@/widgets/composer/lib/attachMenuUtils";
import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useOverlayDismissOnPointer } from "@/shared/lib/hooks/useOverlayDismissOnPointer";
import { getPostMediaItems, postTitle } from "@/shared/lib/helpers";
import { parseAppPath } from "@/shared/lib/routes";
import { usePosts } from "@/entities/post";
import type { ComposerAttachment } from "@/shared/types";

export type AttachScope = "home" | "gchat" | "post" | "feed";

type Pos =
  | { mode: "up"; bottom: number; left: number }
  | { mode: "down"; top: number; left: number };

type Props = {
  scope: AttachScope;
  placement?: "up" | "down";
  attachments?: ComposerAttachment[];
  onAttach: (att: ComposerAttachment) => void;
};

export function useAttachMenu({
  scope,
  placement = "up",
  attachments = [],
  onAttach,
}: Props) {
  const pathname = usePathname() ?? "/";
  const route = parseAppPath(pathname);
  const currentPostId = route.screen === "post" ? route.postId : null;
  const { data: posts = [] } = usePosts();
  const [open, setOpen] = useState(false);
  const [submenu, setSubmenu] = useState<AttachSubmenuKey>(null);
  const [pos, setPos] = useState<Pos | null>(null);

  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const updatePos = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    if (placement === "down") {
      setPos({ mode: "down", top: r.bottom + 6, left: r.left });
    } else {
      setPos({ mode: "up", bottom: window.innerHeight - r.top + 6, left: r.left });
    }
  }, [placement]);

  useLayoutEffect(() => {
    if (open) updatePos();
  }, [open, updatePos]);

  const closeMenu = useCallback(() => {
    setOpen(false);
    setSubmenu(null);
  }, []);

  const { consumeSuppressTriggerClick } = useOverlayDismissOnPointer({
    open,
    onClose: closeMenu,
    contentRef: dropdownRef,
    triggerRef: btnRef,
  });

  useFloatingPanelScrollListeners({
    open,
    onReflow: updatePos,
    onClose: closeMenu,
  });

  const pickFile = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onFilePicked = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        onAttach({ id: nextAttachMenuId(), kind: "file", name: file.name, file });
        closeMenu();
      }
      e.target.value = "";
    },
    [closeMenu, onAttach],
  );

  const onTriggerClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (consumeSuppressTriggerClick()) return;
      if (scope === "feed") {
        pickFile();
        return;
      }
      setOpen((v) => !v);
      setSubmenu(null);
    },
    [consumeSuppressTriggerClick, pickFile, scope],
  );

  const currentPost =
    scope === "post" && currentPostId != null
      ? posts.find((p) => p.id === currentPostId) ?? null
      : null;
  const postMedia = currentPost ? getPostMediaItems(currentPost) : [];
  const attachedPostIds = attachments
    .filter((a): a is Extract<ComposerAttachment, { kind: "post" }> => a.kind === "post")
    .map((a) => a.postId);
  const attachedPostsMedia = collectAttachedMedia(posts, attachedPostIds);

  const attachMediaFromPost = useCallback(
    (mediaName: string) => {
      if (!currentPost) return;
      onAttach({
        id: nextAttachMenuId(),
        kind: "media",
        postId: currentPost.id,
        postTitle: postTitle(currentPost),
        media: mediaName,
      });
      closeMenu();
    },
    [closeMenu, currentPost, onAttach],
  );

  const attachMediaFromPinned = useCallback(
    (item: { postId: string; postTitle: string; media: { name: string } }) => {
      onAttach({
        id: nextAttachMenuId(),
        kind: "media",
        postId: item.postId,
        postTitle: item.postTitle,
        media: item.media.name,
      });
      closeMenu();
    },
    [closeMenu, onAttach],
  );

  return {
    scope,
    open,
    pos,
    submenu,
    setSubmenu,
    wrapRef,
    btnRef,
    dropdownRef,
    fileInputRef,
    onTriggerClick,
    onFilePicked,
    pickFile,
    closeMenu,
    currentPost,
    postMedia,
    attachedPostIds,
    attachedPostsMedia,
    attachMediaFromPost,
    attachMediaFromPinned,
  };
}
