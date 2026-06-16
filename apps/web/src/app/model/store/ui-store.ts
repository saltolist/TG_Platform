import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import {
  FEED_POST_WIDTHS,
  type FeedPostWidth,
  isFeedPostWidth,
} from "@/shared/lib/feedPostWidth";

export type { FeedPostWidth as FeedCardWidth };

export type DirtyKey =
  | "note"
  | "profile-channel"
  | "profile-ai"
  | "profile-prompt"
  | "profile-telegram";

const PROFILE_DIRTY_KEYS: DirtyKey[] = [
  "profile-channel",
  "profile-ai",
  "profile-prompt",
  "profile-telegram",
];

const SIDEBAR_COLLAPSED_STORAGE_KEY = "tg-platform-sidebar-collapsed";

const initialDirtyMap: Record<DirtyKey, boolean> = {
  note: false,
  "profile-channel": false,
  "profile-ai": false,
  "profile-prompt": false,
  "profile-telegram": false,
};

export type UiState = {
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebarCollapsed: () => void;
  mobileSidebarOpen: boolean;
  setMobileSidebarOpen: (open: boolean) => void;
  feedCardWidth: FeedPostWidth;
  setFeedCardWidth: (width: FeedPostWidth) => void;
  noteDirty: boolean;
  setNoteDirty: (dirty: boolean) => void;
  dirtyMap: Record<DirtyKey, boolean>;
  setDirty: (key: DirtyKey, dirty: boolean) => void;
  clearProfileDirtyFlags: () => void;
  clearNoteDirty: () => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      toggleSidebarCollapsed: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      mobileSidebarOpen: false,
      setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
      feedCardWidth: FEED_POST_WIDTHS[0],
      setFeedCardWidth: (width) => {
        if (!isFeedPostWidth(width)) return;
        set({ feedCardWidth: width });
      },
      noteDirty: false,
      setNoteDirty: (noteDirty) =>
        set((state) => ({
          noteDirty,
          dirtyMap: { ...state.dirtyMap, note: noteDirty },
        })),
      dirtyMap: initialDirtyMap,
      setDirty: (key, dirty) =>
        set((state) => {
          if (state.dirtyMap[key] === dirty) return state;
          const dirtyMap = { ...state.dirtyMap, [key]: dirty };
          return {
            dirtyMap,
            noteDirty: key === "note" ? dirty : state.noteDirty,
          };
        }),
      clearProfileDirtyFlags: () =>
        set((state) => {
          const dirtyMap = { ...state.dirtyMap };
          for (const key of PROFILE_DIRTY_KEYS) dirtyMap[key] = false;
          return { dirtyMap };
        }),
      clearNoteDirty: () =>
        set((state) => ({
          noteDirty: false,
          dirtyMap: { ...state.dirtyMap, note: false },
        })),
    }),
    {
      name: SIDEBAR_COLLAPSED_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ sidebarCollapsed: state.sidebarCollapsed }),
    },
  ),
);

export function useUi() {
  const dirtyMap = useUiStore((s) => s.dirtyMap);
  const setDirty = useUiStore((s) => s.setDirty);
  const noteDirty = useUiStore((s) => s.noteDirty);
  const clearProfileDirtyFlags = useUiStore((s) => s.clearProfileDirtyFlags);
  const clearNoteDirty = useUiStore((s) => s.clearNoteDirty);
  const sidebarCollapsed = useUiStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useUiStore((s) => s.setSidebarCollapsed);
  const toggleSidebarCollapsed = useUiStore((s) => s.toggleSidebarCollapsed);
  const mobileSidebarOpen = useUiStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useUiStore((s) => s.setMobileSidebarOpen);
  const feedCardWidth = useUiStore((s) => s.feedCardWidth);
  const setFeedCardWidth = useUiStore((s) => s.setFeedCardWidth);
  const setNoteDirty = useUiStore((s) => s.setNoteDirty);

  const profileChannelDirty = dirtyMap["profile-channel"];
  const profileSettingsDirty =
    dirtyMap["profile-ai"] || dirtyMap["profile-prompt"] || dirtyMap["profile-telegram"];
  const profileDirty = profileChannelDirty || profileSettingsDirty;

  return {
    setDirty,
    noteDirty,
    profileChannelDirty,
    profileSettingsDirty,
    profileDirty,
    clearProfileDirtyFlags,
    clearNoteDirty,
    sidebarCollapsed,
    setSidebarCollapsed,
    toggleSidebarCollapsed,
    mobileSidebarOpen,
    setMobileSidebarOpen,
    feedCardWidth,
    setFeedCardWidth,
    setNoteDirty,
  };
}
