"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useNavigationStore } from "@/app/model/store";
import { usePostNavigationStore } from "@/app/model/store/post-navigation-store";
import { useCreatePost, usePosts } from "@/entities/post";
import {
  buildFeedPostSections,
  canSubmitFeedDraft,
  createDraftPost,
} from "@/shared/lib/feed/filterPosts";
import {
  clampScrollTop,
  getFeedScrollTop,
  getFeedSessionDidInitialScroll,
  markFeedSessionInitialScrollDone,
  setFeedScrollTop,
} from "@/shared/lib/feed/feedScrollSession";
import { isFeedPath } from "@/shared/lib/feed/isFeedPath";
import { buildPublishedFeedDayGroups } from "@/shared/lib/feedTimeline";
import { readFileAsMedia } from "@/shared/lib/helpers";
import type { PostTextContent } from "@/shared/lib/telegram/richTextEditorDom";
import { serializeRichTextEditor } from "@/shared/lib/telegram/richTextEditorDom";
import { isListQueryBootstrapping } from "@/shared/lib/query/isQueryBootstrapping";
import { routes } from "@/shared/lib/routes";
import type { PostMedia } from "@/shared/types";
import { useFeedPostLayout } from "@/widgets/feed";

export function useFeedScreen() {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const onFeed = isFeedPath(pathname);
  const search = useNavigationStore((s) => s.feedSearch);
  const feedShowDeleted = useNavigationStore((s) => s.feedShowDeleted);
  const setNav = useNavigationStore((s) => s.setNav);
  const { data: posts = [], isLoading } = usePosts();
  const showPostsLoading = isListQueryBootstrapping(isLoading, posts);
  const createPost = useCreatePost();
  const setPostMode = usePostNavigationStore((s) => s.setMode);
  const { layoutClassName, layoutStyle } = useFeedPostLayout();

  const [draft, setDraft] = useState<PostTextContent>({ text: "" });
  const [pendingMedia, setPendingMedia] = useState<PostMedia[]>([]);
  const [composerReady, setComposerReady] = useState(false);

  const editorRef = useRef<HTMLDivElement>(null);
  const feedScrollRef = useRef<HTMLDivElement>(null);

  const { published, scheduled, deleted, drafts } = useMemo(
    () => buildFeedPostSections(posts, search, { showDeleted: feedShowDeleted }),
    [feedShowDeleted, posts, search],
  );
  const publishedDayGroups = useMemo(
    () => buildPublishedFeedDayGroups(published),
    [published],
  );

  useEffect(() => {
    const el = feedScrollRef.current;
    if (!el || !onFeed) return;
    const onScroll = () => setFeedScrollTop(el.scrollTop);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [onFeed]);

  useLayoutEffect(() => {
    const el = feedScrollRef.current;
    if (!el || !onFeed || showPostsLoading) return;

    setComposerReady(false);

    const maxScroll = () => Math.max(0, el.scrollHeight - el.clientHeight);

    const pinToBottom = () => {
      el.scrollTop = maxScroll();
      setFeedScrollTop(el.scrollTop);
    };

    const restoreScroll = () => {
      el.scrollTop = clampScrollTop(getFeedScrollTop(), el.scrollHeight, el.clientHeight);
    };

    const syncScroll = () => {
      if (!getFeedSessionDidInitialScroll()) {
        if (maxScroll() > 0) {
          pinToBottom();
          markFeedSessionInitialScrollDone();
        }
        return;
      }
      restoreScroll();
    };

    syncScroll();

    const scrollBody = el.querySelector<HTMLElement>(".composer-scroll-body");
    let ro: ResizeObserver | null = null;
    if (scrollBody) {
      ro = new ResizeObserver(() => syncScroll());
      ro.observe(scrollBody);
    }

    let raf1 = 0;
    let raf2 = 0;
    raf1 = requestAnimationFrame(() => {
      syncScroll();
      raf2 = requestAnimationFrame(() => {
        syncScroll();
        setComposerReady(true);
      });
    });

    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      ro?.disconnect();
    };
  }, [onFeed, search, showPostsLoading]);

  const submitDraft = useCallback(() => {
    const content: PostTextContent = editorRef.current
      ? serializeRichTextEditor(editorRef.current)
      : draft;
    if (!canSubmitFeedDraft(content.text, pendingMedia.length)) return;
    const newPost = createDraftPost({
      text: content.text,
      textHtml: content.textHtml,
      pendingMedia,
    });
    createPost.mutate(newPost);
    setDraft({ text: "" });
    setPendingMedia([]);
  }, [createPost, draft, pendingMedia]);

  const removePendingMedia = useCallback((index: number) => {
    setPendingMedia((arr) => arr.filter((_, i) => i !== index));
  }, []);

  const handleDraftKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitDraft();
      }
      if (e.key === "Backspace" && !draft.text && pendingMedia.length > 0) {
        e.preventDefault();
        setPendingMedia((arr) => arr.slice(0, -1));
      }
    },
    [draft.text, pendingMedia.length, submitDraft],
  );

  const handleAttach = useCallback(async (att: { kind: string; file?: File }) => {
    if (att.kind === "file" && att.file) {
      try {
        const media = await readFileAsMedia(att.file);
        setPendingMedia((arr) => [...arr, media]);
      } catch {
        /* ignore read errors */
      }
    }
  }, []);

  const openPost = useCallback(
    (id: string) => {
      usePostNavigationStore.getState().setPendingNewPostChat(id, true);
      setPostMode(id, "chat", null);
      setNav({ isEditing: false });
      router.push(routes.post(id));
    },
    [router, setNav, setPostMode],
  );

  const openPostComments = useCallback(
    (id: string) => {
      setPostMode(id, "comments");
      router.push(routes.post(id));
    },
    [router, setPostMode],
  );

  return {
    data: {
      publishedDayGroups,
      scheduled,
      deleted,
      drafts,
      isLoading: showPostsLoading,
      isEmpty:
        published.length === 0 &&
        scheduled.length === 0 &&
        drafts.length === 0 &&
        (!feedShowDeleted || deleted.length === 0),
    },
    ui: {
      layoutClassName,
      layoutStyle,
      composerReady,
      editorRef,
      draft,
      setDraft,
      pendingMedia,
      feedScrollRef,
    },
    actions: {
      openPost,
      openPostComments,
      submitDraft,
      removePendingMedia,
      handleDraftKeyDown,
      handleAttach,
    },
  };
}

export type FeedScreenState = ReturnType<typeof useFeedScreen>;
