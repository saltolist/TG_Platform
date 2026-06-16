"use client";

import { BranchChevronIcon } from "@/entities/message";
import AiMsgModelHint from "@/widgets/chat-thread/ui/AiMsgModelHint";

type Props = {
  modelTitle: string;
  canGoPrev: boolean;
  canGoNext: boolean;
  onPrev: () => void;
  onNext: () => void;
};

export default function ChatAiVariantNav({
  modelTitle,
  canGoPrev,
  canGoNext,
  onPrev,
  onNext,
}: Props) {
  return (
    <div className="msg-user-branch-row msg-ai-variant-row">
      <button
        type="button"
        className="msg-user-branch-arrow"
        aria-label={canGoPrev ? "Предыдущая модель" : "Предыдущей модели нет"}
        title={canGoPrev ? "Предыдущая модель" : "Предыдущей модели нет"}
        disabled={!canGoPrev}
        onClick={onPrev}
      >
        <BranchChevronIcon dir="left" />
      </button>
      <AiMsgModelHint modelTitle={modelTitle} />
      <button
        type="button"
        className="msg-user-branch-arrow"
        aria-label={canGoNext ? "Следующая модель" : "Следующей модели нет"}
        title={canGoNext ? "Следующая модель" : "Следующей модели нет"}
        disabled={!canGoNext}
        onClick={onNext}
      >
        <BranchChevronIcon dir="right" />
      </button>
    </div>
  );
}
