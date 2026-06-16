"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { useNavigationStore } from "@/app/model/store/navigation-store";
import { useGlobalNotes } from "@/entities/note";
import { usePosts } from "@/entities/post";
import { createNewGlobalNote, createNewPostNote } from "@/shared/lib/noteDraft";
import { parseAppPath } from "@/shared/lib/routes";
import type { ActiveNote } from "@/shared/types";
import { isListQueryBootstrapping } from "@/shared/lib/query/isQueryBootstrapping";
import { routeNeedsCachedData } from "@/widgets/app-shell/lib/syncRoute";

function noteFromCache(
  parsed: ReturnType<typeof parseAppPath>,
  notePostId: string | null,
  globalNotes: ReturnType<typeof useGlobalNotes>["data"],
  posts: ReturnType<typeof usePosts>["data"],
): ActiveNote | null {
  if (parsed.noteIsNew) {
    if (notePostId) {
      return createNewPostNote(notePostId);
    }
    return createNewGlobalNote();
  }
  if (parsed.noteGlobalId) {
    const n = globalNotes?.find((x) => x.id === parsed.noteGlobalId);
    if (!n) return null;
    const files = Array.isArray(n.files) ? n.files : [];
    return { ...n, isGlobal: true, files };
  }
  if (parsed.notePostId != null && parsed.noteId != null) {
    const post = posts?.find((p) => p.id === parsed.notePostId);
    const n = post?.notes.find((x) => x.id === parsed.noteId);
    if (!n || !post) return null;
    const files = Array.isArray(n.files) ? n.files : [];
    return { ...n, isGlobal: false, postId: parsed.notePostId, files };
  }
  return null;
}

/** Resolve active note from nav store or React Query cache (URL is source of truth). */
export function useNoteFromRoute(pathname: string) {
  const searchParams = useSearchParams();
  const parsed = parseAppPath(pathname);
  const notePostIdParam = searchParams.get("postId");
  const storeNote = useNavigationStore((s) => s.currentNote);

  const { data: globalNotes, isLoading: globalNotesLoading } = useGlobalNotes();
  const { data: posts, isLoading: postsLoading } = usePosts();

  const cachedNote = useMemo(() => {
    const route = parseAppPath(pathname);
    return noteFromCache(
      route,
      notePostIdParam ?? null,
      globalNotes,
      posts,
    );
  }, [globalNotes, notePostIdParam, pathname, posts]);

  const note = storeNote ?? cachedNote;
  const needsCache = routeNeedsCachedData(pathname);
  const globalNotesBootstrapping = isListQueryBootstrapping(globalNotesLoading, globalNotes);
  const postsBootstrapping = isListQueryBootstrapping(postsLoading, posts);
  const queriesLoading =
    (parsed.noteGlobalId ? globalNotesBootstrapping : false) ||
    (parsed.notePostId != null && parsed.noteId != null ? postsBootstrapping : false);
  const loading = needsCache && !note && queriesLoading;

  return { note, loading, parsed };
}
