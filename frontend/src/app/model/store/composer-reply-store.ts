import { create } from "zustand";

import type { ComposerScope } from "@/shared/types";

type ActiveReply = {
  scope: ComposerScope;
  controller: AbortController;
};

type ComposerReplyState = {
  active: ActiveReply | null;
  beginReply: (scope: ComposerScope) => AbortSignal;
  stopReply: () => void;
  endReply: () => void;
  isActiveForScope: (scope: ComposerScope) => boolean;
};

export const useComposerReplyStore = create<ComposerReplyState>((set, get) => ({
  active: null,
  beginReply: (scope) => {
    get().active?.controller.abort();
    const controller = new AbortController();
    set({ active: { scope, controller } });
    return controller.signal;
  },
  stopReply: () => {
    get().active?.controller.abort();
  },
  endReply: () => {
    set({ active: null });
  },
  isActiveForScope: (scope) => get().active?.scope === scope,
}));
