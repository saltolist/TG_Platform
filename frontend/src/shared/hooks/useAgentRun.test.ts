/**
 * @vitest-environment jsdom
 */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const streamAgentRun = vi.fn();
const apiRequest = vi.fn();

vi.mock("@/shared/api/agentRuns", () => ({
  streamAgentRun: (...args: unknown[]) => streamAgentRun(...args),
}));
vi.mock("@/shared/api/httpClient", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

import { useAgentRun } from "./useAgentRun";

afterEach(() => {
  streamAgentRun.mockReset();
  apiRequest.mockReset();
});

describe("useAgentRun reconnect loop", () => {
  it("stops reconnecting once the run is completed", async () => {
    streamAgentRun.mockResolvedValue(undefined);
    apiRequest.mockResolvedValue({
      id: "r1",
      thread_id: "t1",
      status: "completed",
      scope: "post",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    renderHook(() => useAgentRun({ runId: "r1" }));

    await waitFor(() => expect(streamAgentRun).toHaveBeenCalled());
    // Let any reconnect backoff (500ms) elapse, then confirm the count is
    // stable: a completed run must break the loop, not keep reconnecting.
    await new Promise((r) => setTimeout(r, 800));
    const settled = streamAgentRun.mock.calls.length;
    await new Promise((r) => setTimeout(r, 800));
    expect(streamAgentRun.mock.calls.length).toBe(settled);
  });

  it("keeps reconnecting while interrupted (awaiting HITL decision)", async () => {
    streamAgentRun.mockResolvedValue(undefined);
    apiRequest.mockResolvedValue({
      id: "r2",
      thread_id: "t2",
      status: "interrupted",
      scope: "post",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    renderHook(() => useAgentRun({ runId: "r2" }));

    // interrupted is not terminal => it polls again after the 500ms backoff.
    await waitFor(() => expect(streamAgentRun.mock.calls.length).toBeGreaterThan(1), {
      timeout: 2000,
    });
  });
});
