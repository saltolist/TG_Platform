"use client";

import { BranchChevronIcon } from "@/entities/message";

type Props = {
  index: number;
  count: number;
  canGoPrev: boolean;
  canGoNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  prevLabel: string;
  nextLabel: string;
  className?: string;
  countClassName?: string;
};

export default function ChatBranchNav({
  index,
  count,
  canGoPrev,
  canGoNext,
  onPrev,
  onNext,
  prevLabel,
  nextLabel,
  className = "msg-user-branch-row",
  countClassName = "msg-user-branch-count",
}: Props) {
  return (
    <div className={className}>
      <button
        type="button"
        className="msg-user-branch-arrow"
        aria-label={canGoPrev ? prevLabel : `${prevLabel} нет`}
        title={canGoPrev ? prevLabel : `${prevLabel} нет`}
        disabled={!canGoPrev}
        onClick={onPrev}
      >
        <BranchChevronIcon dir="left" />
      </button>
      <span className={countClassName}>
        {index + 1}/{count}
      </span>
      <button
        type="button"
        className="msg-user-branch-arrow"
        aria-label={canGoNext ? nextLabel : `${nextLabel} нет`}
        title={canGoNext ? nextLabel : `${nextLabel} нет`}
        disabled={!canGoNext}
        onClick={onNext}
      >
        <BranchChevronIcon dir="right" />
      </button>
    </div>
  );
}
