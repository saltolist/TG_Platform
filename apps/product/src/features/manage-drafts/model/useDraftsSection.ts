"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent as ReactDragEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { usePosts, useReorderPosts } from "@/entities/post";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  appendZoneBottom,
  buildDraftDisplayList,
  collectDraftDragItems,
  slotBoundariesForVisible,
  stabilizeSlot,
  yToRawSlot,
} from "@/shared/lib/drafts/draftDnDUtils";
import type { Post } from "@/shared/types";

export function useDraftsSection(drafts: Post[], onOpenPost: (id: string) => void) {
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const { data: posts = [] } = usePosts();
  const reorderPosts = useReorderPosts();

  const containerRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const draggingIdRef = useRef<string | null>(null);
  const dropBeforeIdRef = useRef<string | null>(null);
  const committedSlotRef = useRef<number | null>(null);
  const gapHeightRef = useRef(120);

  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropBeforeId, setDropBeforeId] = useState<string | null>(null);
  const [gapHeight, setGapHeight] = useState(120);

  const dragGhostRef = useRef<HTMLElement | null>(null);

  const setDropTarget = useCallback((beforeId: string | null) => {
    dropBeforeIdRef.current = beforeId;
    setDropBeforeId((prev) => (prev === beforeId ? prev : beforeId));
  }, []);

  const onDocumentDragOverForFeedScroll = useCallback((e: DragEvent) => {
    if (draggingIdRef.current == null) return;
    const feed = document.getElementById("feed-scroll") as HTMLElement | null;
    if (!feed) return;
    const y = e.clientY;
    const vh = window.innerHeight;
    const fr = feed.getBoundingClientRect();
    const EDGE_VIEW = 80;
    const INNER = 56;
    const MAX_STEP = 26;
    let delta = 0;
    if (y < EDGE_VIEW) {
      delta = -Math.ceil((MAX_STEP * (EDGE_VIEW - y)) / EDGE_VIEW);
    } else if (y < fr.top + INNER) {
      const span = Math.max(1, fr.top + INNER);
      delta = -Math.ceil((MAX_STEP * (span - y)) / INNER);
    } else if (y > vh - EDGE_VIEW) {
      delta = Math.ceil((MAX_STEP * (y - (vh - EDGE_VIEW))) / EDGE_VIEW);
    } else if (y > fr.bottom - INNER) {
      const span = Math.max(1, INNER);
      delta = Math.ceil((MAX_STEP * (y - (fr.bottom - INNER))) / span);
    }
    if (delta !== 0) {
      feed.scrollTop += delta;
    }
  }, []);

  const reorder = useCallback(
    (sourceId: string, beforeId: string | null) => {
      if (sourceId === beforeId) return;
      const nextPosts = [...posts];
      const srcIdx = nextPosts.findIndex((p) => p.id === sourceId);
      if (srcIdx === -1) return;
      const [item] = nextPosts.splice(srcIdx, 1);
      let insertAt: number;
      if (beforeId == null) {
        let lastDraftIdx = -1;
        nextPosts.forEach((p, i) => {
          if (p.status === "draft") lastDraftIdx = i;
        });
        insertAt = lastDraftIdx + 1;
      } else {
        insertAt = nextPosts.findIndex((p) => p.id === beforeId);
        if (insertAt < 0) insertAt = nextPosts.length;
      }
      nextPosts.splice(insertAt, 0, item);

      const previous = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId));
      queryClient.setQueryData(queryKeys.posts.list(accountId), nextPosts);
      reorderPosts.mutate(nextPosts, {
        onError: () => {
          if (previous) queryClient.setQueryData(queryKeys.posts.list(accountId), previous);
        },
      });
    },
    [accountId, posts, queryClient, reorderPosts],
  );

  const updateDropTarget = useCallback(
    (clientY: number) => {
      const dragId = draggingIdRef.current;
      if (dragId == null) return;

      const visibleDrafts = drafts.filter((d) => d.id !== dragId);
      const items = collectDraftDragItems(visibleDrafts, cardRefs.current);

      if (visibleDrafts.length === 0) {
        setDropTarget(null);
        return;
      }

      const slotCount = items.length + 1;
      const appendBottom = appendZoneBottom(items, containerRef.current);
      const boundaries = slotBoundariesForVisible(items, appendBottom);
      const raw = yToRawSlot(clientY, boundaries, slotCount);
      const slot = stabilizeSlot(clientY, raw, boundaries, slotCount, committedSlotRef.current);
      committedSlotRef.current = slot;

      const beforeId = slot >= items.length ? null : items[slot]!.id;
      setDropTarget(beforeId);
    },
    [drafts, setDropTarget],
  );

  const onDocumentDragOverForDraftDrop = useCallback(
    (e: DragEvent) => {
      if (draggingIdRef.current == null) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
      updateDropTarget(e.clientY);
    },
    [updateDropTarget],
  );

  const activeDropHandlerRef = useRef<((e: DragEvent) => void) | null>(null);

  const removeAllDragListeners = useCallback(() => {
    document.removeEventListener("dragover", onDocumentDragOverForFeedScroll);
    document.removeEventListener("dragover", onDocumentDragOverForDraftDrop);
    if (activeDropHandlerRef.current) {
      document.removeEventListener("drop", activeDropHandlerRef.current);
      activeDropHandlerRef.current = null;
    }
  }, [onDocumentDragOverForFeedScroll, onDocumentDragOverForDraftDrop]);

  const onDocumentDropForDraft = useCallback(
    (e: DragEvent) => {
      if (draggingIdRef.current == null) return;
      e.preventDefault();
      const dragId = draggingIdRef.current;
      reorder(dragId, dropBeforeIdRef.current);
      draggingIdRef.current = null;
      setDraggingId(null);
      setDropTarget(null);
      committedSlotRef.current = null;
      dragGhostRef.current?.remove();
      dragGhostRef.current = null;
      removeAllDragListeners();
    },
    [reorder, setDropTarget, removeAllDragListeners],
  );

  const clearDrag = useCallback(() => {
    removeAllDragListeners();
    draggingIdRef.current = null;
    setDraggingId(null);
    setDropTarget(null);
    committedSlotRef.current = null;
    dragGhostRef.current?.remove();
    dragGhostRef.current = null;
  }, [removeAllDragListeners, setDropTarget]);

  const onDragStart = (id: string) => (e: ReactDragEvent) => {
    e.stopPropagation();

    const wrap = cardRefs.current.get(id);
    if (!wrap) return;

    draggingIdRef.current = id;
    committedSlotRef.current = null;
    dropBeforeIdRef.current = id;

    const style = getComputedStyle(wrap);
    const marginBottom = parseFloat(style.marginBottom) || 0;
    const h = wrap.offsetHeight + marginBottom;
    gapHeightRef.current = h;
    setGapHeight(h);

    e.dataTransfer.effectAllowed = "move";
    try {
      e.dataTransfer.setData("text/plain", id);
    } catch {
      /* ignore */
    }

    dragGhostRef.current?.remove();
    const ghost = wrap.cloneNode(true) as HTMLElement;
    ghost.classList.add("draft-drag-preview");
    ghost.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
    ghost.querySelectorAll("[draggable]").forEach((el) => el.removeAttribute("draggable"));

    const rect = wrap.getBoundingClientRect();
    ghost.style.boxSizing = "border-box";
    ghost.style.position = "fixed";
    ghost.style.left = `${rect.left}px`;
    ghost.style.top = `${rect.top}px`;
    ghost.style.width = `${rect.width}px`;
    ghost.style.pointerEvents = "none";
    ghost.style.margin = "0";
    ghost.style.zIndex = "2147483647";
    document.body.appendChild(ghost);
    void ghost.offsetHeight;

    const gr = ghost.getBoundingClientRect();
    let hx = e.clientX - gr.left;
    let hy = e.clientY - gr.top;
    const w = Math.max(1, gr.width);
    const gh = Math.max(1, gr.height);
    hx = Math.max(0, Math.min(hx, w - 1));
    hy = Math.max(0, Math.min(hy, gh - 1));

    try {
      e.dataTransfer.setDragImage(ghost, hx, hy);
      dragGhostRef.current = ghost;
    } catch {
      ghost.remove();
      dragGhostRef.current = null;
    }

    document.addEventListener("dragover", onDocumentDragOverForFeedScroll);
    document.addEventListener("dragover", onDocumentDragOverForDraftDrop);
    document.addEventListener("drop", onDocumentDropForDraft);
    activeDropHandlerRef.current = onDocumentDropForDraft;

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (draggingIdRef.current !== id) return;
        setDraggingId(id);
        setDropBeforeId(id);
        if (dragGhostRef.current) {
          dragGhostRef.current.style.left = "-9999px";
          dragGhostRef.current.style.top = "0";
        }
      });
    });
  };

  const onDragEnd = () => {
    clearDrag();
  };

  const onDraftsDragOver = (e: ReactDragEvent) => {
    if (draggingIdRef.current == null) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    updateDropTarget(e.clientY);
  };

  const onDrop = (e: ReactDragEvent) => {
    if (draggingIdRef.current == null) return;
    e.preventDefault();
    e.stopPropagation();
    onDocumentDropForDraft(e.nativeEvent);
  };

  useEffect(() => {
    return () => {
      removeAllDragListeners();
    };
  }, [removeAllDragListeners]);

  const displayItems = useMemo(
    () => buildDraftDisplayList(drafts, draggingId, dropBeforeId),
    [drafts, draggingId, dropBeforeId],
  );

  return {
    openPost: onOpenPost,
    containerRef,
    cardRefs,
    draggingId,
    gapHeight,
    displayItems,
    onDraftsDragOver,
    onDrop,
    onDragStart,
    onDragEnd,
  };
}
