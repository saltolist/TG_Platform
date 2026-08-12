import { create } from "zustand";

import { cancelAgentRun } from "@/shared/api/agentRuns";
import type { ComposerScope } from "@/shared/types";

type ActiveReply = {
  scope: ComposerScope;
  controller: AbortController;
  runId?: string;
};

type ComposerReplyState = {
  active: ActiveReply | null;
  lastRunIdByScope: Partial<Record<ComposerScope, string>>;
  beginReply: (scope: ComposerScope) => AbortSignal;
  setRunId: (scope: ComposerScope, runId: string | null) => void;
  stopReply: () => void;
  endReply: () => void;
  isActiveForScope: (scope: ComposerScope) => boolean;
};

export const useComposerReplyStore = create<ComposerReplyState>((set, get) => ({
  active: null,
  lastRunIdByScope: {},
  beginReply: (scope) => {
    get().active?.controller.abort();
    const controller = new AbortController();
    set({ active: { scope, controller } });
    return controller.signal;
  },
  setRunId: (scope, runId) => {
    const active = get().active;
    set({
      active: active?.scope === scope ? { ...active, runId: runId ?? undefined } : active,
      lastRunIdByScope: {
        ...get().lastRunIdByScope,
        [scope]: runId ?? undefined,
      },
    });
  },
  stopReply: () => {
    const active = get().active;
    active?.controller.abort();
    if (active?.runId) void cancelAgentRun(active.runId);
  },
  endReply: () => {
    set({ active: null });
  },
  isActiveForScope: (scope) => get().active?.scope === scope,
}));
