"use client";

import PostStatus from "@/entities/post/ui/PostStatus";
import type { Post } from "@/shared/types";

export function PostStatusBadge({
  post,
  syncing = false,
}: {
  post: Post;
  syncing?: boolean;
}) {
  return <PostStatus post={post} syncing={syncing} />;
}
