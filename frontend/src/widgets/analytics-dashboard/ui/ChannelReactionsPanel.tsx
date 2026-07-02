"use client";

import { PostReactionPills } from "@/widgets/feed";
import type { PostReaction } from "@/shared/types";

const DEMO_REACTIONS: PostReaction[] = [
  { emoji: "🔥", count: 412 },
  { emoji: "❤️", count: 134 },
  { emoji: "👍", count: 222 },
  { emoji: "🤔", count: 34 },
];

export default function ChannelReactionsPanel({
  reactions,
}: {
  reactions?: PostReaction[];
}) {
  const items = reactions?.length ? reactions : DEMO_REACTIONS;
  return (
    <div className="channel-reactions-panel" aria-label="Популярные реакции">
      <PostReactionPills reactions={items} />
    </div>
  );
}
