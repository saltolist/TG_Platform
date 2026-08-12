"use client";

import type { AgentProposal } from "@/shared/api/schemas/agentRun";
import type { Post } from "@/shared/types";
import { PostMediaBlock, PostStatusBadge } from "@/entities/post";
import { TelegramFormattedText } from "@/shared/ui/TelegramFormattedText";
import { postTitle } from "@/shared/lib/postTitle";
import { buildProposalPostPreview } from "@/widgets/agent/lib/proposalPostPreview";

export type ProposalDecision = "approve" | "reject";

type Props = {
  proposal: AgentProposal;
  currentPost: Post | null;
  /** null while pending; "approve" | "reject" once the user decided. */
  decision: ProposalDecision | null;
  collapsed: boolean;
  onDecide: (decision: ProposalDecision) => void;
  onToggle: () => void;
};

export function PostProposalCard({
  proposal,
  currentPost,
  decision,
  collapsed,
  onDecide,
  onToggle,
}: Props) {
  const { post, changeLabel } = buildProposalPostPreview(proposal, currentPost);
  const title = postTitle(post);
  const decided = decision !== null;

  if (decided && collapsed) {
    return (
      <button
        type="button"
        className="post-proposal-collapsed"
        onClick={onToggle}
        aria-expanded={false}
        data-testid="post-proposal-card"
        data-decision={decision}
      >
        <span
          className={`post-proposal-collapsed__dot post-proposal-collapsed__dot--${decision}`}
          aria-hidden
        />
        <span className="post-proposal-collapsed__title">{title}</span>
        <ProposalChevron expanded={false} />
      </button>
    );
  }

  return (
    <div
      className="post-proposal post-msg-block"
      data-testid="post-proposal-card"
      data-decision={decision ?? "pending"}
    >
      <div
        className="post-proposal__head"
        role={decided ? "button" : undefined}
        tabIndex={decided ? 0 : undefined}
        onClick={decided ? onToggle : undefined}
        onKeyDown={
          decided
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onToggle();
                }
              }
            : undefined
        }
      >
        <span className="post-proposal__label">{changeLabel}</span>
        {decided ? <ProposalChevron expanded /> : null}
      </div>
      <div className="post-card post-msg-card post-proposal__card">
        <div className="post-card-body">
          {post.media && post.media.length > 0 ? (
            <div className="post-card-media">
              <PostMediaBlock media={post.media} />
            </div>
          ) : null}
          {post.text || post.textHtml ? (
            <TelegramFormattedText
              text={post.text}
              textHtml={post.textHtml}
              className="post-card-text"
            />
          ) : (
            <div className="post-card-text empty">Пост пустой</div>
          )}
          <div className="post-card-footer">
            <div className="post-meta">
              <PostStatusBadge post={post} />
            </div>
          </div>
        </div>
      </div>
      {decided ? null : (
        <div className="post-proposal__actions">
          <button
            type="button"
            className="btn btn-primary post-edit-btn"
            onClick={() => onDecide("approve")}
          >
            Подтвердить
          </button>
          <button
            type="button"
            className="btn btn-ghost post-edit-btn"
            onClick={() => onDecide("reject")}
          >
            Отменить
          </button>
        </div>
      )}
    </div>
  );
}

function ProposalChevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={`post-proposal__chevron${expanded ? " is-expanded" : ""}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
