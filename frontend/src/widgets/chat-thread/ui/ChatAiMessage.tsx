"use client";

import ChatMarkdown from "@/shared/ui/ChatMarkdown";
import AiMessageToolbar from "./AiMessageToolbar";
import AiTypingIndicator from "./AiTypingIndicator";
import ChatAiVariantNav from "./ChatAiVariantNav";
import type { ChatMessageCtx } from "@/entities/message";
import { useGlobalNotes } from "@/entities/note";
import { usePosts } from "@/entities/post";
import { buildValidNoteCitationPaths } from "@/shared/lib/buildValidNoteCitationPaths";
import { useMemo } from "react";

type Props = {
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
  const { data: posts = [] } = usePosts();
  const { data: globalNotes = [] } = useGlobalNotes();
  const validNotePaths = useMemo(
    () => buildValidNoteCitationPaths(globalNotes, posts),
    [globalNotes, posts],
  );
  const showTyping = isStreaming && !plainAi.trim();
  const showMultiStreamingNav = isStreaming && showVariantNav && !!ctx;
  const showFooter = !isStreaming || showMultiStreamingNav;

  return (
    <div className="msg-row ai">
      <div className="msg-body">
        {showTyping ? (
          <AiTypingIndicator />
        ) : (
          <div className="msg-text">
            <ChatMarkdown text={plainAi} validNotePaths={validNotePaths} />
          </div>
        )}
        {showFooter ? (
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
            {!isStreaming ? (
              <AiMessageToolbar
                plainText={plainAi}
                modelTitle={showVariantNav ? undefined : modelTitle}
                onDelete={onDelete}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
