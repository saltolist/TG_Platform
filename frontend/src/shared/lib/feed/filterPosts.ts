import { postTitle } from "@/shared/lib/helpers";
import { sortPostsByPublicationTime } from "@/shared/lib/feedTimeline";
import { randomId } from "@/shared/lib/randomId";
import type { Post, PostMedia, PostStatus } from "@/shared/types";

export function normalizeSearchQuery(query: string): string {
  return query.trim().toLowerCase();
}

export function postMatchesSearch(post: Post, query: string): boolean {
  const q = normalizeSearchQuery(query);
  if (!q) return true;
  return (
    postTitle(post).toLowerCase().includes(q) ||
    (post.text || "").toLowerCase().includes(q)
  );
}

export function filterPostsByStatus(
  posts: Post[],
  status: PostStatus,
  query = "",
): Post[] {
  return posts.filter((p) => p.status === status && postMatchesSearch(p, query));
}

export type FeedPostSections = {
  published: Post[];
  scheduled: Post[];
  deleted: Post[];
  drafts: Post[];
};

export function buildFeedPostSections(
  posts: Post[],
  query = "",
  options: { showDeleted?: boolean } = {},
): FeedPostSections {
  const active = posts.filter((p) => p.status !== "deleted");
  const deleted = options.showDeleted
    ? sortPostsByPublicationTime(
        filterPostsByStatus(posts, "deleted", query),
        "desc",
      )
    : [];

  return {
    published: filterPostsByStatus(active, "published", query),
    scheduled: sortPostsByPublicationTime(
      filterPostsByStatus(active, "scheduled", query),
      "asc",
    ),
    deleted,
    drafts: filterPostsByStatus(active, "draft", query),
  };
}

export type CreateDraftPostInput = {
  text: string;
  pendingMedia?: PostMedia[];
  id?: string;
  created?: string;
};

export function createDraftPost({
  text,
  pendingMedia = [],
  id = randomId(),
  created = new Date().toISOString(),
}: CreateDraftPostInput): Post {
  const trimmed = text.trim();
  return {
    id,
    status: "draft",
    created,
    rubric: null,
    text: trimmed,
    notes: [],
    chats: [],
    ...(pendingMedia.length > 0 ? { media: [...pendingMedia] } : {}),
  };
}

export function canSubmitFeedDraft(text: string, pendingMediaCount: number): boolean {
  return text.trim().length > 0 || pendingMediaCount > 0;
}
