"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, type MutableRefObject } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { useUiStore } from "@/app/model/store";
import { useNavigationStore } from "@/app/model/store/navigation-store";
import type { RouteNavigationPatch } from "@/app/model/store/navigation/types";
import { usePostNavigationStore } from "@/app/model/store/post-navigation-store";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { queryKeys } from "@/shared/api/queryKeys";
import { recordAppNavigation } from "@/shared/lib/appNavStack";
import {
  isNoteRouteDataQuery,
  mergeNoteCachePatch,
  routeNeedsCachedData,
  routeSyncKey,
  syncPostModeFromRoute,
  syncRouteFromUrl,
} from "@/widgets/app-shell/lib/syncRoute";
import type { GlobalChat, GlobalNote, Post, PostMode } from "@/shared/types";

function applyRouteSync(
  path: string,
  searchParams: URLSearchParams,
  queryClient: QueryClient,
  accountId: string,
  syncKeyRef: MutableRefObject<string>,
  postModeOverrideRef: MutableRefObject<PostMode | null>,
  router: ReturnType<typeof useRouter>,
  setNav: (patch: RouteNavigationPatch) => void,
  setPostMode: ReturnType<typeof usePostNavigationStore.getState>["setMode"],
  options: { urlDedup: boolean },
): void {
  const syncKey = routeSyncKey(path, searchParams);
  if (options.urlDedup) {
    if (syncKeyRef.current === syncKey) return;
    syncKeyRef.current = syncKey;
  }

  const posts = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId)) ?? [];
  const globalChats =
    queryClient.getQueryData<GlobalChat[]>(queryKeys.globalChats.list(accountId)) ?? [];
  const globalNotes =
    queryClient.getQueryData<GlobalNote[]>(queryKeys.globalNotes.list(accountId)) ?? [];

  const result = syncRouteFromUrl(path, searchParams, { posts, globalChats, globalNotes }, {
    postModeOverride: postModeOverrideRef.current,
    getPostMode: (postId) => usePostNavigationStore.getState().getMode(postId),
  });
  postModeOverrideRef.current = null;

  if (result.kind === "redirect") {
    if (result.postMode) {
      postModeOverrideRef.current = result.postMode.mode;
      syncPostModeFromRoute(usePostNavigationStore.getState(), result.postMode);
    }
    router.replace(result.href);
    return;
  }

  if (result.postMode) {
    syncPostModeFromRoute(usePostNavigationStore.getState(), result.postMode);
  }

  let patch = result.patch;
  if (!options.urlDedup) {
    patch = mergeNoteCachePatch(
      useNavigationStore.getState(),
      patch,
      useUiStore.getState().noteDirty,
    );
  }
  setNav(patch);
  recordAppNavigation(path, searchParams);
}

export function RouteSync() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const setNav = useNavigationStore((s) => s.setNav);
  const setPostMode = usePostNavigationStore((s) => s.setMode);
  const syncKeyRef = useRef("");
  const postModeOverrideRef = useRef<PostMode | null>(null);

  useLayoutEffect(() => {
    applyRouteSync(
      pathname ?? "/",
      searchParams,
      queryClient,
      accountId,
      syncKeyRef,
      postModeOverrideRef,
      router,
      setNav,
      setPostMode,
      { urlDedup: true },
    );
  }, [pathname, searchParams, router, queryClient, accountId, setNav, setPostMode]);

  useEffect(() => {
    const path = pathname ?? "/";
    if (!routeNeedsCachedData(path)) return;

    return queryClient.getQueryCache().subscribe((event) => {
      if (event.type !== "updated" || !isNoteRouteDataQuery(path, event.query.queryKey)) return;
      applyRouteSync(
        path,
        searchParams,
        queryClient,
        accountId,
        syncKeyRef,
        postModeOverrideRef,
        router,
        setNav,
        setPostMode,
        { urlDedup: false },
      );
    });
  }, [pathname, searchParams, router, queryClient, accountId, setNav, setPostMode]);

  return null;
}
