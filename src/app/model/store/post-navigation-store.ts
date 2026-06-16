import { create } from "zustand";
import type { PostMode } from "@/shared/types";

export type PostViewEntry = { mode: PostMode; chatId: string | null };

const TAB_MODES: PostMode[] = ["notes", "chats", "comments"];

function resolvePostViewMode(currentMode: PostMode, nextMode: PostMode): PostMode {
  if (TAB_MODES.includes(nextMode) && currentMode === nextMode) {
    return "chat";
  }
  return nextMode;
}

export type PostNavigationState = {
  stacks: Record<string, PostViewEntry[]>;
  modes: Record<string, PostMode>;
  chatIds: Record<string, string | null>;
  getMode: (postId: string) => PostMode;
  getStack: (postId: string) => PostViewEntry[];
  getCurrentPostChatId: (postId: string) => string | null;
  pushMode: (postId: string, mode: PostMode, chatId?: string | null) => void;
  popMode: (postId: string) => void;
  resetStack: (postId: string) => void;
  setMode: (postId: string, mode: PostMode, chatId?: string | null) => void;
};

export const usePostNavigationStore = create<PostNavigationState>((set, get) => ({
  stacks: {},
  modes: {},
  chatIds: {},

  getMode: (postId) => get().modes[postId] ?? "chat",
  getStack: (postId) => get().stacks[postId] ?? [],
  getCurrentPostChatId: (postId) => get().chatIds[postId] ?? null,

  pushMode: (postId, mode, chatId = null) => {
    const currentMode = get().getMode(postId);
    const currentChatId = get().getCurrentPostChatId(postId);
    set((state) => ({
      stacks: {
        ...state.stacks,
        [postId]: [...(state.stacks[postId] ?? []), { mode: currentMode, chatId: currentChatId }],
      },
      modes: { ...state.modes, [postId]: mode },
      chatIds: {
        ...state.chatIds,
        [postId]: mode === "chat" ? chatId : null,
      },
    }));
  },

  popMode: (postId) => {
    const stack = get().getStack(postId);
    if (stack.length === 0) return;
    const previous = stack[stack.length - 1]!;
    set((state) => ({
      stacks: { ...state.stacks, [postId]: stack.slice(0, -1) },
      modes: { ...state.modes, [postId]: previous.mode },
      chatIds: { ...state.chatIds, [postId]: previous.chatId },
    }));
  },

  resetStack: (postId) => {
    set((state) => ({
      stacks: { ...state.stacks, [postId]: [] },
    }));
  },

  setMode: (postId, nextMode, chatId = null) => {
    const currentMode = get().getMode(postId);
    const mode = resolvePostViewMode(currentMode, nextMode);
    let resolvedChatId: string | null = null;
    if (mode === "chat") {
      resolvedChatId = nextMode === "chat" ? chatId : get().getCurrentPostChatId(postId);
    }
    set((state) => ({
      modes: { ...state.modes, [postId]: mode },
      chatIds: { ...state.chatIds, [postId]: resolvedChatId },
      stacks: { ...state.stacks, [postId]: [] },
    }));
  },
}));
