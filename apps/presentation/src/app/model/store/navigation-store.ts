import { create } from "zustand";

import {
  initialNavigationState,
  type NavigationPatch,
  type NavigationState,
  type RouteNavigationPatch,
} from "@/app/model/store/navigation/types";
import type { AnalyticsPeriod } from "@/shared/data/analytics-seed";
import type { ChatsTab, NoteListFilter, NoteScope } from "@/shared/types";

export function applyNavigationPatch(
  state: NavigationState,
  patch: RouteNavigationPatch,
): NavigationState {
  const { screen, ...rest } = patch;
  const next = { ...state, ...rest };
  if (screen !== undefined && screen !== "post") {
    next.isEditing = false;
  }
  return next;
}

export type NavigationStore = NavigationState & {
  setNav: (patch: RouteNavigationPatch) => void;
  setChatsTab: (tab: ChatsTab) => void;
  setChatsSearch: (chatsSearch: string) => void;
  setNoteScope: (scope: NoteScope) => void;
  setNoteFilter: (filter: NoteListFilter) => void;
  setNotesSearch: (notesSearch: string) => void;
  setFeedSearch: (feedSearch: string) => void;
  setAnalyticsPeriod: (analyticsPeriod: AnalyticsPeriod) => void;
};

export const useNavigationStore = create<NavigationStore>((set) => ({
  ...initialNavigationState,
  setNav: (patch) => set((state) => applyNavigationPatch(state, patch)),
  setChatsTab: (chatsTab) => set({ chatsTab }),
  setChatsSearch: (chatsSearch) => set({ chatsSearch }),
  setNoteScope: (noteScope) => set({ noteScope }),
  setNoteFilter: (noteFilter) => set({ noteFilter }),
  setNotesSearch: (notesSearch) => set({ notesSearch }),
  setFeedSearch: (feedSearch) => set({ feedSearch }),
  setAnalyticsPeriod: (analyticsPeriod) => set({ analyticsPeriod }),
}));
