import { create } from "zustand";

import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";
import {
  readStoredComposerTarget,
  writeStoredComposerTarget,
  type StoredComposerTarget,
} from "@/shared/lib/composerTargetStorage";
import type { ComposerScope } from "@/shared/types";

type ComposerTarget = { llmId: string; webId: string };

type ComposerTargetState = {
  targets: Record<ComposerScope, ComposerTarget>;
  setLlmId: (scope: ComposerScope, llmId: string) => void;
  setWebId: (scope: ComposerScope, webId: string) => void;
  getTarget: (scope: ComposerScope) => ComposerTarget;
  hydrateForAccount: (accountId: string) => void;
  resetTargets: () => void;
};

const defaultTarget = (): ComposerTarget => ({ llmId: "", webId: "" });

function targetFromSaved(saved: StoredComposerTarget | null): ComposerTarget {
  return {
    llmId: saved?.llmId ?? "",
    webId: saved?.webId ?? "",
  };
}

function allScopesTarget(target: ComposerTarget): Record<ComposerScope, ComposerTarget> {
  return {
    home: { ...target },
    gchat: { ...target },
    post: { ...target },
  };
}

function initialTargets(): Record<ComposerScope, ComposerTarget> {
  if (typeof window === "undefined") {
    return allScopesTarget(defaultTarget());
  }
  return allScopesTarget(targetFromSaved(readStoredComposerTarget(getQueryAccountIdFromAuth())));
}

function persistTarget(target: ComposerTarget): void {
  writeStoredComposerTarget(getQueryAccountIdFromAuth(), target);
}

function syncTarget(
  state: ComposerTargetState,
  scope: ComposerScope,
  patch: Partial<ComposerTarget>,
): Record<ComposerScope, ComposerTarget> {
  const current = state.targets[scope] ?? defaultTarget();
  return allScopesTarget({ ...current, ...patch });
}

export const useComposerTargetStore = create<ComposerTargetState>((set, get) => ({
  targets: initialTargets(),
  hydrateForAccount: (accountId) => {
    const saved = typeof window === "undefined" ? null : readStoredComposerTarget(accountId);
    set({ targets: allScopesTarget(targetFromSaved(saved)) });
  },
  resetTargets: () => {
    get().hydrateForAccount(getQueryAccountIdFromAuth());
  },
  setLlmId: (scope, llmId) => {
    const targets = syncTarget(get(), scope, { llmId });
    set({ targets });
    persistTarget(targets[scope]);
  },
  setWebId: (scope, webId) => {
    const targets = syncTarget(get(), scope, { webId });
    set({ targets });
    persistTarget(targets[scope]);
  },
  getTarget: (scope) => get().targets[scope] ?? defaultTarget(),
}));
