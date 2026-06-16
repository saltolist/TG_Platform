"use client";

import { PostCard } from "@/widgets/feed";
import type { Post } from "@/shared/types";

type Props = {
  posts: Post[];
  onOpen: (id: string) => void;
};

export function FeedScheduledSection({ posts, onOpen }: Props) {
  if (posts.length === 0) return null;

  return (
    <div className="feed-section">
      <div className="section-label">Отложенные</div>
      <div className="feed-section-cards">
        {posts.map((p) => (
          <PostCard key={p.id} post={p} onOpen={() => onOpen(p.id)} />
        ))}
      </div>
    </div>
  );
}
