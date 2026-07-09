"use client";

import ChatMarkdown from "@/shared/ui/ChatMarkdown";
import AiMessageToolbar from "./AiMessageToolbar";
import AiTypingIndicator from "./AiTypingIndicator";
import ChatAiVariantNav from "./ChatAiVariantNav";
import type { ChatMessageCtx } from "@/entities/message";
import { useGlobalNotes } from "@/entities/note";
import { usePosts } from "@/entities/post";
import { buildNoteCitationTitlesByPath, buildValidNoteCitationPaths } from "@/shared/lib/buildValidNoteCitationPaths";
import {
  buildValidPathsFromKbCites,
  mergeKbCiteTitles,
  prepareNoteCitationsForDisplay,
  stripSelfPostCitations,
} from "@/shared/lib/noteCitation";
import { useMemo } from "react";
import type { KbCite, WebCite } from "@/shared/api/schemas/post";

type Props = {
  plainAi: string;
  modelTitle: string;
  webCites?: WebCite[];
  kbCites?: KbCite[];
  postId?: string;
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
  webCites,
  kbCites,
  postId,
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
  const noteTitleByPath = useMemo(
    () => buildNoteCitationTitlesByPath(globalNotes, posts),
    [globalNotes, posts],
  );
  const validNotePaths = useMemo(() => {
    if (kbCites?.length) return buildValidPathsFromKbCites(kbCites);
    return buildValidNoteCitationPaths(globalNotes, posts);
  }, [globalNotes, posts, kbCites]);
  const displayTitleByPath = useMemo(
    () => (kbCites?.length ? mergeKbCiteTitles(noteTitleByPath, kbCites) : noteTitleByPath),
    [noteTitleByPath, kbCites],
  );
  const displayAi = useMemo(() => {
    let text = prepareNoteCitationsForDisplay(plainAi, validNotePaths, displayTitleByPath);
    if (postId) {
      const post = posts.find((item) => item.id === postId);
      const selfIds = [postId, post?.telegramMessageId].filter(Boolean) as string[];
      text = stripSelfPostCitations(text, selfIds);
    }
    return text;
  }, [plainAi, validNotePaths, displayTitleByPath, postId, posts]);
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
            <ChatMarkdown
              text={displayAi}
              validNotePaths={validNotePaths}
              noteTitleByPath={displayTitleByPath}
              webCites={webCites}
            />
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
