import type { AgentProposal } from "@/shared/api/schemas/agentRun";
import type { Post, PostMedia, PostStatus } from "@/shared/types";

/** Commands that mutate a post and can be previewed as a post card. */
export const POST_PROPOSAL_COMMANDS = new Set([
  "create_post",
  "edit_post",
  "schedule_post",
  "cancel_schedule",
  "publish_post",
  "delete_post",
  "restore_post",
  "attach_media",
]);

export function proposalPostId(proposal: AgentProposal): string | null {
  const preview = (proposal.preview ?? {}) as Record<string, unknown>;
  const direct = preview.post_id ?? preview.id;
  return typeof direct === "string" && direct ? direct : null;
}

/** Status a command lands the post in, or `null` to keep the current one. */
function commandStatus(command: string): PostStatus | null {
  if (command === "publish_post") return "published";
  if (command === "schedule_post") return "scheduled";
  if (command === "delete_post") return "deleted";
  if (command === "cancel_schedule" || command === "restore_post") return "draft";
  return null;
}

export type ProposalPostPreview = {
  post: Post;
  /** Human-readable summary of what changes (текст / статус / медиа). */
  changeLabel: string;
};

const EMPTY_POST: Post = {
  id: "",
  status: "draft",
  rubric: null,
  text: "",
  notes: [],
  chats: [],
};

/** Build the modified version of the post that a proposal would produce. */
export function buildProposalPostPreview(
  proposal: AgentProposal,
  current: Post | null,
): ProposalPostPreview {
  const preview = (proposal.preview ?? {}) as Record<string, unknown>;
  const patch = { ...(preview.patch as Record<string, unknown> | undefined) };
  const data = { ...(preview.data as Record<string, unknown> | undefined) };
  const merged: Post = {
    ...EMPTY_POST,
    ...(current ?? {}),
    id: current?.id ?? proposalPostId(proposal) ?? "",
  };

  const changes: string[] = [];

  const nextText = (patch.text ?? data.text) as string | undefined;
  if (typeof nextText === "string" && nextText !== merged.text) {
    merged.text = nextText;
    changes.push("текст");
  }
  // textHtml renders in preference to text (TelegramFormattedText). An agent
  // edit_post rewrites plain `text` and sends textHtml:null to clear the stale
  // formatted version — otherwise the card shows the pre-edit wording despite
  // the new text (chat 49a569c8). Honour the explicit null, mirroring the
  // executor and applyPostPatch.
  if ("textHtml" in patch && patch.textHtml === null) {
    delete merged.textHtml;
  } else {
    const nextHtml = (patch.textHtml ?? data.textHtml) as string | undefined;
    if (typeof nextHtml === "string") merged.textHtml = nextHtml;
  }

  const nextMedia = (patch.media ?? data.media ?? preview.media) as PostMedia[] | undefined;
  if (Array.isArray(nextMedia)) {
    merged.media = nextMedia;
    changes.push("медиа");
  }

  const nextStatus = commandStatus(proposal.command) ?? (data.status as PostStatus | undefined);
  if (nextStatus && nextStatus !== merged.status) {
    merged.status = nextStatus;
    changes.push("статус");
  }
  const nextDate = (preview.scheduled_at ?? patch.date ?? data.date) as string | undefined;
  if (typeof nextDate === "string") merged.date = nextDate;

  const changeLabel = changes.length ? `Изменено: ${changes.join(", ")}` : "Изменённая версия поста";
  return { post: merged, changeLabel };
}
