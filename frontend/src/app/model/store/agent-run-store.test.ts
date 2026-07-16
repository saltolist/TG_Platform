/**
 * @vitest-environment jsdom
 */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useAgentRun = vi.fn();
const resumeAgentRun = vi.fn();
const getAgentMediaJob = vi.fn();
const showToast = vi.fn();
const useRepositories = vi.fn();
const useQueryClient = vi.fn();

vi.mock("@/shared/hooks/useAgentRun", () => ({ useAgentRun: (...a: unknown[]) => useAgentRun(...a) }));
vi.mock("@/shared/api/agentRuns", () => ({
  resumeAgentRun: (...a: unknown[]) => resumeAgentRun(...a),
  getAgentMediaJob: (...a: unknown[]) => getAgentMediaJob(...a),
}));
vi.mock("@/shared/ui/toast", () => ({ showToast: (...a: unknown[]) => showToast(...a) }));
vi.mock("@/app/providers/RepositoryProvider", () => ({
  useRepositories: (...a: unknown[]) => useRepositories(...a),
}));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: (...a: unknown[]) => useQueryClient(...a) }));
vi.mock("@/entities/post/lib/patchPostChatHistory", () => ({ patchPostChatHistory: vi.fn() }));
vi.mock("@/entities/chat/lib/patchGlobalChatHistory", () => ({ patchGlobalChatHistory: vi.fn() }));

import { ApiError } from "@/shared/api/httpClient";
import { useAgentRunStore } from "./agent-run-store";

afterEach(() => {
  useAgentRun.mockReset();
  resumeAgentRun.mockReset();
  getAgentMediaJob.mockReset();
  showToast.mockReset();
  useRepositories.mockReset();
  useQueryClient.mockReset();
});

function setup(run: Record<string, unknown> | null = null) {
  useAgentRun.mockReturnValue({
    run,
    events: [],
    error: null,
    refresh: vi.fn().mockResolvedValue(run),
  });
  useRepositories.mockReturnValue({ posts: [], chats: [] });
  useQueryClient.mockReturnValue({});
}

describe("useAgentRunStore.resume", () => {
  it("surfaces the backend's error message via toast and keeps the card actionable on failure", async () => {
    setup({ id: "r1", current_interrupt: null });
    resumeAgentRun.mockRejectedValue(
      new ApiError("boom", 400, { detail: "Некорректная дата публикации" }),
    );

    const { result } = renderHook(() => useAgentRunStore("r1", null));
    const outcome = await result.current.resume({ decision: "approve" });

    expect(outcome).toBeNull();
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Некорректная дата публикации", variant: "error" }),
    );
  });

  it("clears pending state and returns the response on success", async () => {
    setup({ id: "r1", current_interrupt: null });
    resumeAgentRun.mockResolvedValue({ ok: true });

    const { result } = renderHook(() => useAgentRunStore("r1", null));
    const outcome = await result.current.resume({ decision: "approve" });

    expect(outcome).toEqual({ ok: true });
    expect(showToast).not.toHaveBeenCalled();
    await waitFor(() => expect(result.current.pendingProposal).toBeNull());
  });
});
