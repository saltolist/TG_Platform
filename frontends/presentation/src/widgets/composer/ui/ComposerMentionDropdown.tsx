"use client";

import { attachmentPostTitle, postStatusLabel, truncate } from "@/shared/lib/helpers";
import type { Post } from "@/shared/types";

export type MentionPos =
  | { mode: "up"; bottom: number; left: number; width: number }
  | { mode: "down"; top: number; left: number; width: number };

type Props = {
  mentionRef: React.RefObject<HTMLDivElement | null>;
  mentionPos: MentionPos;
  matches: Post[];
  activeIndex: number;
  onHoverIndex: (index: number) => void;
  onPick: (post: Post) => void;
};

export default function ComposerMentionDropdown({
  mentionRef,
  mentionPos,
  matches,
  activeIndex,
  onHoverIndex,
  onPick,
}: Props) {
  return (
    <div
      ref={mentionRef}
      className={`mention-dropdown mention-dropdown-${mentionPos.mode}`}
      style={
        mentionPos.mode === "down"
          ? { top: mentionPos.top, left: mentionPos.left, width: mentionPos.width }
          : { bottom: mentionPos.bottom, left: mentionPos.left, width: mentionPos.width }
      }
      onMouseDown={(e) => e.preventDefault()}
    >
      <div className="mention-hint">Прикрепить пост</div>
      {matches.map((p, i) => (
        <div
          key={p.id}
          className={`mention-item${i === activeIndex ? " active" : ""}`}
          onMouseEnter={() => onHoverIndex(i)}
          onClick={() => onPick(p)}
        >
          <span className="mention-item-body">
            <span className="mention-item-title">{truncate(attachmentPostTitle(p), 48)}</span>
            <span className="mention-item-meta">{postStatusLabel(p)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
