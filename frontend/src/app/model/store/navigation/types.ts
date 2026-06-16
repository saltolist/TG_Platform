import type { AnalyticsPeriod } from "@/shared/data/analytics-seed";
import type {
  ActiveNote,
  ChatsTab,
  NoteFromScreen,
  NoteListFilter,
  NoteMode,
  NoteScope,
  ScreenId,
} from "@/shared/types";

export type NavigationState = {
  currentPostId: string | null;
  isEditing: boolean;
  currentNote: ActiveNote | null;
  noteMode: NoteMode;
  noteFrom: NoteFromScreen;
  noteSavedSnapshot: string;
  chatsTab: ChatsTab;
  chatsSearch: string;
  noteScope: NoteScope;
  noteFilter: NoteListFilter;
  notesSearch: string;
  feedSearch: string;
  analyticsPeriod: AnalyticsPeriod;
};

export const initialNavigationState: NavigationState = {
  currentPostId: null as string | null,
  isEditing: false,
  currentNote: null,
  noteMode: "view",
  noteFrom: "notes",
  noteSavedSnapshot: "",
  chatsTab: "all",
  chatsSearch: "",
  noteScope: "all",
  noteFilter: "all",
  notesSearch: "",
  feedSearch: "",
  analyticsPeriod: "30d",
};

export type NavigationPatch = Partial<NavigationState>;

/** Route sync patch: `screen` is transient (side-effects only, not stored). */
export type RouteNavigationPatch = NavigationPatch & {
  screen?: ScreenId;
};
