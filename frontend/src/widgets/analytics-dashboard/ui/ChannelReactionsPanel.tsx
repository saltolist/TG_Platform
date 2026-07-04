"use client";

import { PostReactionPills } from "@/widgets/feed";
import { shouldPersistLocally } from "@/shared/lib/overlay/isOverlayAccount";
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
  const items = reactions?.length
    ? reactions
    : shouldPersistLocally()
      ? DEMO_REACTIONS
      : [];
  return (
    <div className="channel-reactions-panel" aria-label="Популярные реакции">
      {items.length ? (
        <PostReactionPills reactions={items} />
      ) : (
        <p className="channel-reactions-empty">Пока нет реакций на постах</p>
      )}
    </div>
  );
}
