import type { ScreenId } from "@/shared/types";

type PostRowRoute = {
  postId: string | null;
  notePostId: string | null;
  postChatId: string | null;
};

export function resolveSidebarPostId(
  screen: ScreenId,
  postId: string | null,
  notePostId: string | null,
): string | null {
  if (screen === "post" && postId != null) return postId;
  if (screen === "note" && notePostId != null) return notePostId;
  return null;
}

export function shouldShowFeedPostRow(
  sidebarPostId: string | null,
  screen: ScreenId,
  notePostId: string | null,
): boolean {
  return sidebarPostId != null && (screen === "post" || (screen === "note" && notePostId != null));
}

export function isSidebarPostFullActive(
  sidebarPostId: string | null,
  screen: ScreenId,
  route: PostRowRoute,
): boolean {
  return (
    sidebarPostId != null &&
    screen === "post" &&
    route.postId === sidebarPostId &&
    route.postChatId == null
  );
}

export function isSidebarPostSubActive(
  sidebarPostId: string | null,
  screen: ScreenId,
  route: PostRowRoute,
): boolean {
  if (sidebarPostId == null) return false;
  if (isSidebarPostFullActive(sidebarPostId, screen, route)) return false;
  return (
    (screen === "post" &&
      route.postId === sidebarPostId &&
      route.postChatId != null) ||
    (screen === "note" && route.notePostId === sidebarPostId)
  );
}
