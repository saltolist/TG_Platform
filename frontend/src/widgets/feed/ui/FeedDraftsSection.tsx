"use client";

import { useDraftsSection } from "@/features/manage-drafts";
import type { Post } from "@/shared/types";

import DraftsCardStack from "./drafts/DraftsCardStack";

type Props = {
  drafts: Post[];
  onOpen: (id: string) => void;
};

export function FeedDraftsSection({ drafts, onOpen }: Props) {
  const ds = useDraftsSection(drafts, onOpen);

  if (drafts.length === 0) return null;

  return (
    <div className="feed-section">
      <div className="section-label">Черновики</div>
      <DraftsCardStack
        containerRef={ds.containerRef}
        cardRefs={ds.cardRefs}
        draggingId={ds.draggingId}
        gapHeight={ds.gapHeight}
        displayItems={ds.displayItems}
        onDraftsDragOver={ds.onDraftsDragOver}
        onDrop={ds.onDrop}
        onDragStart={ds.onDragStart}
        onDragEnd={ds.onDragEnd}
        onOpenPost={ds.openPost}
      />
    </div>
  );
}
