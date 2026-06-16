"use client";

import PostStatus from "@/entities/post/ui/PostStatus";
import type { Post } from "@/shared/types";

export function PostStatusBadge({ post }: { post: Post }) {
  return <PostStatus post={post} />;
}
