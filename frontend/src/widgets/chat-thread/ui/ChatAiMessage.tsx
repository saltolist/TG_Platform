"use client";

import AiMessageToolbar from "./AiMessageToolbar";
import AiTypingIndicator from "./AiTypingIndicator";
import ChatAiVariantNav from "./ChatAiVariantNav";
import type { ChatMessageCtx } from "@/entities/message";

type Props = {
  textHtml: string;
  plainAi: string;
  modelTitle: string;
  ctx?: ChatMessageCtx;
  showVariantNav: boolean;
  canGoVariantPrev: boolean;
  canGoVariantNext: boolean;
  onBumpVariant: (delta: number) => void;
  onDelete?: () => void;
  isStreaming?: boolean;
};

export default function ChatAiMessage({
  textHtml,
  plainAi,
  modelTitle,
  ctx,
  showVariantNav,
  canGoVariantPrev,
  canGoVariantNext,
  onBumpVariant,
  onDelete,
  isStreaming = false,
}: Props) {
  const showTyping = isStreaming && !plainAi.trim();

  return (
    <div className="msg-row ai">
      <div className="msg-body">
        {showTyping ? (
          <AiTypingIndicator />
        ) : (
          <div className="msg-text" dangerouslySetInnerHTML={{ __html: textHtml }} />
        )}
        {!isStreaming ? (
          <div className="ai-msg-footer">
            <div className="ai-msg-footer-left">
              {showVariantNav && ctx ? (
                <ChatAiVariantNav
                  modelTitle={modelTitle}
                  canGoPrev={canGoVariantPrev}
                  canGoNext={canGoVariantNext}
                  onPrev={() => onBumpVariant(-1)}
                  onNext={() => onBumpVariant(1)}
                />
              ) : null}
            </div>
            <AiMessageToolbar plainText={plainAi} onDelete={onDelete} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
