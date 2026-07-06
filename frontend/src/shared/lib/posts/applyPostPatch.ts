import type { PostPatch } from "@/shared/api/repositories";
import type { Post } from "@/shared/types";

export function applyPostPatch(post: Post, patch: PostPatch): Post {
  const { textHtml, ...restPatch } = patch;
  const next: Post = { ...post, ...restPatch };
  if (textHtml === null) {
    delete next.textHtml;
  } else if (textHtml !== undefined) {
    next.textHtml = textHtml;
  }
  return next;
}
