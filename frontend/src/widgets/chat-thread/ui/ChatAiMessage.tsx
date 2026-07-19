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
import { useCallback, useMemo, useState } from "react";
import type { KbCite, WebCite } from "@/shared/api/schemas/post";
import type { AgentProposal, MessageArtifactRef, MessageContextRef } from "@/shared/api/schemas/agentRun";
import { useAgentRunContext } from "@/widgets/agent/model/AgentRunContext";
import { selectCurrentToolLabel } from "@/widgets/agent/lib/agentActivityLabel";
import { getCachedPost } from "@/entities/post/lib/getCachedPost";
import { useQueryClient } from "@tanstack/react-query";
import { AgentProposalCard } from "@/widgets/agent/ui/AgentProposalCard";
import { PostProposalCard, type ProposalDecision } from "@/widgets/agent/ui/PostProposalCard";
import {
  POST_PROPOSAL_COMMANDS,
  proposalPostId,
} from "@/widgets/agent/lib/proposalPostPreview";

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
  // Snapshot of the action_proposal card born on this turn, if any (persisted
  // by agent-run-store so it survives a reload) — rendered inline, in this
  // turn's own slot in the thread, instead of only at the bottom.
  proposal?: AgentProposal;
  proposalDecision?: ProposalDecision | null;
  contextRefs?: MessageContextRef[];
  artifacts?: MessageArtifactRef[];
  staleRefs?: Array<Record<string, unknown>>;
  contextProvenance?: "exact" | "inferred" | "legacy";
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
  proposal,
  proposalDecision = null,
  contextRefs = [],
  artifacts = [],
  staleRefs = [],
  contextProvenance,
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

  const agentRun = useAgentRunContext();
  const agentRunId = agentRun?.runId ?? null;
  const agentIsRunning = agentRun?.run?.status === "running";
  const agentEvents = agentRun?.events;
  // While the agent runs, the inline typing indicator carries the live step
  // phrase (workspace_step/planner_step/tool_result) — the single source of
  // "what's happening now". For plain LLM streaming (no agent run / no events)
  // there's no step to show, so it stays as bare dots.
  const typingLabel = useMemo(() => {
    if (!agentRunId || !agentIsRunning || !agentEvents) return undefined;
    return selectCurrentToolLabel(agentEvents);
  }, [agentRunId, agentIsRunning, agentEvents]);
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(true);
  const decide = useCallback(
    (decision: ProposalDecision) => {
      if (!proposal) return;
      void agentRun?.resume({
        decision,
        proposal_id: proposal.id,
        payload_hash: proposal.payload_hash,
      });
    },
    [agentRun, proposal],
  );
  const currentPostForProposal = useMemo(() => {
    if (!proposal) return null;
    const id = proposalPostId(proposal);
    return id ? (getCachedPost(queryClient, id) ?? null) : null;
  }, [proposal, queryClient]);

  return (
    <div className="msg-row ai">
      <div className="msg-body">
        {proposal ? (
          POST_PROPOSAL_COMMANDS.has(proposal.command) ? (
            <PostProposalCard
              proposal={proposal}
              currentPost={currentPostForProposal}
              decision={proposalDecision}
              collapsed={proposalDecision !== null && collapsed}
              onDecide={decide}
              onToggle={() => setCollapsed((v) => !v)}
            />
          ) : (
            <AgentProposalCard
              proposal={proposal}
              onApprove={() => decide("approve")}
              onReject={() => decide("reject")}
            />
          )
        ) : null}
        {showTyping ? (
          <AiTypingIndicator label={typingLabel} />
        ) : plainAi.trim() ? (
          <div className="msg-text">
            <ChatMarkdown
              text={displayAi}
              validNotePaths={validNotePaths}
              noteTitleByPath={displayTitleByPath}
              webCites={webCites}
            />
          </div>
        ) : null}
        {(contextRefs.length > 0 || artifacts.length > 0 || staleRefs.length > 0) ? (
          <div className="ai-context-refs" aria-label="Источники ответа" data-provenance={contextProvenance}>
            {contextRefs.map((item) => (
              <a
                key={item.ref}
                className={`ai-context-chip${item.provenance === "legacy" ? " is-legacy" : ""}`}
                href={item.route || undefined}
                title={item.provenance === "legacy" ? "Источник из старой истории" : item.ref}
              >
                {item.title || (item.kind === "post" ? "Пост" : item.kind === "note" ? "Заметка" : "Источник")}
              </a>
            ))}
            {artifacts.map((item) => (
              <a key={item.ref} className="ai-context-chip artifact" href={item.route || `#${item.ref}`}>
                {item.title || "Материал ответа"}
              </a>
            ))}
            {staleRefs.map((item, index) => (
              <span key={`${String(item.ref || "stale")}-${index}`} className="ai-context-chip stale">
                Источник недоступен
              </span>
            ))}
          </div>
        ) : null}
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
