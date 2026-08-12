import { describe, expect, it } from "vitest";

import type { AgentProposal } from "@/shared/api/schemas/agentRun";
import type { Post } from "@/shared/types";
import { buildProposalPostPreview } from "./proposalPostPreview";

const basePost: Post = {
  id: "p1",
  status: "draft",
  rubric: null,
  text: "Привет",
  textHtml: "<strong>Привет</strong>",
  notes: [],
  chats: [],
};

function editProposal(patch: Record<string, unknown>): AgentProposal {
  return {
    id: "prop1",
    command: "edit_post",
    payload_hash: "h",
    preview: { post_id: "p1", patch },
  };
}

describe("buildProposalPostPreview", () => {
  it("clears stale textHtml when the patch sends textHtml:null (chat 49a569c8)", () => {
    // The post renders textHtml over text; a leftover formatted textHtml made
    // the card show the pre-edit wording. A null patch must drop it so the
    // edited plain text is what the user sees and approves.
    const { post } = buildProposalPostPreview(
      editProposal({ text: "Привет2", textHtml: null }),
      basePost,
    );
    expect(post.text).toBe("Привет2");
    expect(post.textHtml).toBeUndefined();
  });

  it("keeps a provided textHtml string", () => {
    const { post } = buildProposalPostPreview(
      editProposal({ text: "Привет2", textHtml: "<em>Привет2</em>" }),
      basePost,
    );
    expect(post.textHtml).toBe("<em>Привет2</em>");
  });

  it("updates text and reports the change", () => {
    const { post, changeLabel } = buildProposalPostPreview(
      editProposal({ text: "Привет2", textHtml: null }),
      basePost,
    );
    expect(post.text).toBe("Привет2");
    expect(changeLabel).toContain("текст");
  });
});
