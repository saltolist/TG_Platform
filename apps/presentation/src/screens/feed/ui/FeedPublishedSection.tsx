"use client";

import { PostCard } from "@/widgets/feed";
import type { FeedDayGroup } from "@/shared/lib/feedTimeline";

type Props = {
  groups: FeedDayGroup[];
  onOpen: (id: string) => void;
  onOpenComments: (id: string) => void;
};

export function FeedPublishedSection({ groups, onOpen, onOpenComments }: Props) {
  if (groups.length === 0) return null;

  return (
    <div className="feed-section feed-section--published">
      <div className="section-label">Опубликованные</div>
      <div className="feed-section-cards">
        {groups.map((group) => (
          <div className="feed-day-group" key={group.key}>
            <div className="feed-day-marker">
              <span>{group.label}</span>
            </div>
            {group.posts.map((p) => (
              <PostCard
                key={p.id}
                post={p}
                onOpen={() => onOpen(p.id)}
                onOpenComments={() => onOpenComments(p.id)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
