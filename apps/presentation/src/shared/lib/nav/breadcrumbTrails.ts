import { postTitle } from "@/shared/lib/helpers";
import type { BreadcrumbItem } from "@/shared/ui/breadcrumb";
import type { ActiveNote, LocalChat, Post, PostMode } from "@/shared/types";

export type NoteBreadcrumbTrailContext = {
  note: ActiveNote;
  parentPost: Post | null;
  titleLabel?: string;
  onNavigateNotes: () => void;
  onNavigateFeed: () => void;
  onOpenPost: (postId: string) => void;
};

export function buildNoteBreadcrumbTrail({
  note,
  parentPost,
  titleLabel,
  onNavigateNotes,
  onNavigateFeed,
  onOpenPost,
}: NoteBreadcrumbTrailContext): BreadcrumbItem[] {
  const title = titleLabel ?? (note.title || "Новая заметка");

  if (note.isGlobal) {
    return [
      { label: "Заметки", onClick: onNavigateNotes },
      { label: title, current: true, variant: "truncate" },
    ];
  }

  const items: BreadcrumbItem[] = [{ label: "Лента", onClick: onNavigateFeed }];
  if (parentPost) {
    items.push({
      label: postTitle(parentPost),
      onClick: () => onOpenPost(note.postId),
      variant: "title",
    });
  }
  items.push({ label: title, current: true, variant: "truncate" });
  return items;
}

export type GChatBreadcrumbTrailContext = {
  chatTitle: string;
  onNavigateBackToChats: () => void;
};

export function buildGChatBreadcrumbTrail({
  chatTitle,
  onNavigateBackToChats,
}: GChatBreadcrumbTrailContext): BreadcrumbItem[] {
  return [
    { label: "Чаты", onClick: onNavigateBackToChats },
    { label: chatTitle || "—", current: true, variant: "truncate" },
  ];
}

export type PostBreadcrumbTrailContext = {
  post: Post;
  postMode: PostMode;
  currentPostChatId: string | null;
  activeChat: LocalChat | null;
  postSubPage: string | null;
  postIntermediateCrumb: string;
  onNavigateFeed: () => void;
  onOpenPostView: () => void;
  onResetToPostChatRoot: () => void;
};

export function buildPostBreadcrumbTrail({
  post,
  postMode,
  currentPostChatId,
  activeChat,
  postSubPage,
  postIntermediateCrumb,
  onNavigateFeed,
  onOpenPostView,
  onResetToPostChatRoot,
}: PostBreadcrumbTrailContext): BreadcrumbItem[] {
  if (postSubPage) {
    return [
      { label: "Лента", onClick: onNavigateFeed },
      { label: postIntermediateCrumb, onClick: onOpenPostView, variant: "title" },
      { label: postSubPage, current: true },
    ];
  }

  if (postMode === "chat" && currentPostChatId != null && activeChat) {
    return [
      { label: "Лента", onClick: onNavigateFeed },
      { label: postIntermediateCrumb, onClick: onResetToPostChatRoot, variant: "title" },
      { label: activeChat.title, current: true, variant: "truncate" },
    ];
  }

  return [
    { label: "Лента", onClick: onNavigateFeed },
    { label: postTitle(post), current: true, variant: "title" },
  ];
}
