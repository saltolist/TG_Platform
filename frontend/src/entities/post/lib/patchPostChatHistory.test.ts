import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { PostsRepository } from "@/shared/api/repositories";
import type { ChatMessage, Post } from "@/shared/types";

import { patchPostChatHistory } from "./patchPostChatHistory";

vi.mock("@/shared/lib/auth/queryAccountScope", () => ({
  getQueryAccountIdFromAuth: () => "acc",
}));

function makePost(): Post {
  return {
    id: "3",
    text: "body",
    status: "draft",
    date: "now",
    rubric: null,
    media: [],
    notes: [],
    chats: [
      {
        id: "c1",
        title: "t",
        preview: "",
        date: "now",
        ai: true,
        history: [
          { role: "user", text: "add it" },
          { role: "ai", text: "" } as ChatMessage,
        ],
      },
    ],
  };
}

// Server-side chats merge: incoming history replaces stored history for the
// chat (mirrors backend merge_history_stamps — incoming wins per field). Each
// update() reads the CURRENT server state, so a lost update only happens if two
// read-modify-write cycles overlap on the same base snapshot.
function makeRepo(): { repo: PostsRepository; server: { current: Post } } {
  const server = { current: makePost() };
  const repo = {
    list: vi.fn(async () => [server.current]),
    update: vi.fn(async (_id: string, patch: { chats?: Post["chats"] }) => {
      if (patch.chats) server.current = { ...server.current, chats: patch.chats };
      return server.current;
    }),
  } as unknown as PostsRepository;
  return { repo, server };
}

function lastAiOf(post: Post): ChatMessage {
  const history = post.chats[0].history;
  return history[history.length - 1];
}
const setLastAi = (updater: (m: ChatMessage) => ChatMessage) => (history: ChatMessage[]) => {
  const next = [...history];
  next[next.length - 1] = updater(next[next.length - 1]);
  return next;
};

describe("patchPostChatHistory race (mutex)", () => {
  it("concurrent proposal-persist + empty finalize both survive", async () => {
    const qc = new QueryClient();
    const { repo, server } = makeRepo();

    const proposal = { id: "p1", command: "edit_post", payload_hash: "h" };

    // Fire both writes concurrently, as the real SSE flows do:
    //  - agent-run-store persists the proposal card
    //  - composer-store finalizes the (empty) AI turn, preserving any card
    await Promise.all([
      patchPostChatHistory(qc, repo, "3", "c1", setLastAi((m) => ({ ...m, proposal }))),
      patchPostChatHistory(
        qc,
        repo,
        "3",
        "c1",
        setLastAi((m) => ({ ...m, text: "", proposal: m.proposal })),
      ),
    ]);

    // Without serialization the second update() would overwrite the first on a
    // stale snapshot and the proposal would vanish.
    expect(lastAiOf(server.current).proposal).toEqual(proposal);
  });

  it("serializes: no update runs on a stale snapshot", async () => {
    const qc = new QueryClient();
    const { repo, server } = makeRepo();
    const updateSpy = repo.update as ReturnType<typeof vi.fn>;

    await Promise.all([
      patchPostChatHistory(qc, repo, "3", "c1", setLastAi((m) => ({ ...m, proposal: { id: "p1", command: "c", payload_hash: "h" } }))),
      patchPostChatHistory(qc, repo, "3", "c1", setLastAi((m) => ({ ...m, proposalDecision: "reject" }))),
    ]);

    const final = lastAiOf(server.current);
    // Both fields present => the decision write read the proposal write's result.
    expect(final.proposal).toBeDefined();
    expect(final.proposalDecision).toBe("reject");
    expect(updateSpy).toHaveBeenCalledTimes(2);
  });
});
