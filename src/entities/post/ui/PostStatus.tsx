import { CheckIcon, ClockIcon, PencilIcon } from "@/shared/ui/icons/post-status-icons";
import { formatStoredDate } from "@/shared/lib/helpers";
import type { Post } from "@/shared/types";

export function PostStatusIcon({
  post,
  size = "100%",
}: {
  post: Pick<Post, "status">;
  size?: number | string;
}) {
  if (post.status === "published") {
    return (
      <span className="post-status-icon post-status-icon--published" aria-hidden>
        <CheckIcon size={size} />
      </span>
    );
  }
  if (post.status === "scheduled") {
    return (
      <span className="post-status-icon post-status-icon--scheduled" aria-hidden>
        <ClockIcon size={size} />
      </span>
    );
  }
  return (
    <span className="post-status-icon" aria-hidden>
      <PencilIcon size={size} />
    </span>
  );
}

export default function PostStatus({
  post,
}: {
  post: Pick<Post, "status" | "date" | "created">;
}) {
  if (post.status === "published") {
    return (
      <span className="post-status">
        <PostStatusIcon post={post} />
        <span className="post-status-text">
          <span className="post-status-title">Опубликован</span>
          {post.date ? (
            <span className="post-status-time">{formatStoredDate(post.date)}</span>
          ) : null}
        </span>
      </span>
    );
  }
  if (post.status === "scheduled") {
    return (
      <span className="post-status">
        <PostStatusIcon post={post} />
        <span className="post-status-text">
          <span className="post-status-title">Отложено</span>
          {post.date ? (
            <span className="post-status-time">{formatStoredDate(post.date)}</span>
          ) : null}
        </span>
      </span>
    );
  }
  return (
    <span className="post-status">
      <PostStatusIcon post={post} />
      <span className="post-status-text">
        <span className="post-status-title">Черновик</span>
        <span className="post-status-time">создан {formatStoredDate(post.created)}</span>
      </span>
    </span>
  );
}
