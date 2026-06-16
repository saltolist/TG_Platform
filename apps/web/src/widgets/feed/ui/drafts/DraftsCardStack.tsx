"use client";

import type { DragEvent as ReactDragEvent, RefObject } from "react";

import type { DraftDisplayItem } from "@/shared/lib/drafts/draftDnDUtils";
import type { Post } from "@/shared/types";

import PostCard from "../PostCard";

type Props = {
  containerRef: RefObject<HTMLDivElement | null>;
  cardRefs: RefObject<Map<string, HTMLDivElement>>;
  draggingId: string | null;
  gapHeight: number;
  displayItems: DraftDisplayItem[];
  onDraftsDragOver: (e: ReactDragEvent) => void;
  onDrop: (e: ReactDragEvent) => void;
  onDragStart: (id: string) => (e: ReactDragEvent) => void;
  onDragEnd: () => void;
  onOpenPost: (id: string) => void;
};

export default function DraftsCardStack({
  containerRef,
  cardRefs,
  draggingId,
  gapHeight,
  displayItems,
  onDraftsDragOver,
  onDrop,
  onDragStart,
  onDragEnd,
  onOpenPost,
}: Props) {
  return (
    <div
      className={`feed-section-cards draft-cards-stack${draggingId != null ? " draft-cards-stack--dragging" : ""}`}
      ref={containerRef}
      onDragOver={onDraftsDragOver}
      onDrop={onDrop}
    >
      {displayItems.map((item) =>
        item.kind === "gap" ? (
          <div key={item.key} className="draft-drop-gap" style={{ height: gapHeight }} aria-hidden />
        ) : (
          <DraftCardWrap
            key={item.post.id}
            post={item.post}
            cardRefs={cardRefs}
            onOpen={() => onOpenPost(item.post.id)}
            onDragStart={onDragStart(item.post.id)}
            onDragEnd={onDragEnd}
          />
        ),
      )}
    </div>
  );
}

function DraftCardWrap({
  post,
  cardRefs,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  post: Post;
  cardRefs: RefObject<Map<string, HTMLDivElement>>;
  onOpen: () => void;
  onDragStart: (e: ReactDragEvent) => void;
  onDragEnd: () => void;
}) {
  return (
    <div
      className="draft-card-wrap"
      ref={(el) => {
        if (el) cardRefs.current.set(post.id, el);
        else cardRefs.current.delete(post.id);
      }}
      data-draft-id={post.id}
    >
      <PostCard
        post={post}
        onOpen={onOpen}
        draftHandleProps={{
          onClickStop: (ev) => ev.stopPropagation(),
          onDragStart,
          onDragEnd,
        }}
      />
    </div>
  );
}
