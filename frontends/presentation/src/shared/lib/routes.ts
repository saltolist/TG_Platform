import {
  buildNoteSnapshot,
  createNewGlobalNote,
  createNewPostNote,
  EMPTY_NOTE_SNAPSHOT,
} from "@/shared/lib/noteDraft";
import type {
  ActiveNote,
  GlobalChat,
  GlobalNote,
  NoteFromScreen,
  Post,
  PostMode,
  ScreenId,
} from "@/shared/types";

export const POST_NEW_SLUG = "new";
export const NOTE_NEW_SLUG = "new";
export const GCHAT_ID_PARAM = "id";

export type ParsedAppPath = {
  screen: ScreenId;
  postId: string | null;
  postMode: PostMode;
  gchatId: string | null;
  noteGlobalId: string | null;
  notePostId: string | null;
  noteId: string | null;
  noteIsNew: boolean;
  chatId: string | null;
};

function norm(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.endsWith("/") ? pathname : `${pathname}/`;
}

/** Parse a URL path segment into an ID string. Returns null for empty/reserved segments. */
function parseSegmentId(s: string | undefined): string | null {
  if (!s || s === "new") return null;
  return s;
}

export function parseAppPath(pathname: string): ParsedAppPath {
  const path = norm(pathname);
  const empty: ParsedAppPath = {
    screen: "home",
    postId: null,
    postMode: "chat",
    gchatId: null,
    noteGlobalId: null,
    notePostId: null,
    noteId: null,
    noteIsNew: false,
    chatId: null,
  };
  if (path === "/") return empty;

  const segments = path.split("/").filter(Boolean);

  if (segments[0] === "feed") return { ...empty, screen: "feed" };
  if (segments[0] === "chats") return { ...empty, screen: "chats" };
  if (segments[0] === "notes") return { ...empty, screen: "notes" };
  if (segments[0] === "analytics") return { ...empty, screen: "analytics" };
  if (segments[0] === "profile") return { ...empty, screen: "profile" };

  if (segments[0] === "gchat") {
    if (segments[1]) {
      return { ...empty, screen: "gchat", gchatId: decodeURIComponent(segments[1]) };
    }
    return { ...empty, screen: "gchat" };
  }

  if (segments[0] === "post" && segments[1]) {
    const postId = parseSegmentId(segments[1]);
    if (!postId) return empty;
    return {
      ...empty,
      screen: "post",
      postId,
      postMode: "chat",
    };
  }

  if (segments[0] === "note") {
    if (segments[1] === NOTE_NEW_SLUG) {
      return { ...empty, screen: "note", noteIsNew: true };
    }
    if (segments[1] === "global" && segments[2]) {
      return { ...empty, screen: "note", noteGlobalId: segments[2] };
    }
    if (segments[1] === "post" && segments[2] && segments[3]) {
      const notePostId = parseSegmentId(segments[2]);
      const noteId = parseSegmentId(segments[3]);
      if (notePostId && noteId) {
        return { ...empty, screen: "note", notePostId, noteId };
      }
    }
  }

  return empty;
}

/** Старые URL `/post/5/notes/` → редирект на `/post/5/` + режим во state. */
export function parsePostLegacySub(
  pathname: string,
): { postId: string; mode: PostMode } | null {
  const path = norm(pathname);
  const m = path.match(/^\/post\/([^/]+)\/(comments|notes|chats)\/$/);
  if (!m || m[1] === POST_NEW_SLUG) return null;
  const postId = parseSegmentId(m[1]);
  if (!postId) return null;
  const mode = m[2] as "comments" | "notes" | "chats";
  return { postId, mode };
}

export function parseChatSearchParam(raw: string | null): string | null {
  if (!raw) return null;
  const id = raw.trim();
  return id.length > 0 ? id : null;
}

export function parseGChatSearchParam(raw: string | null): string | null {
  if (!raw) return null;
  const id = raw.trim();
  return id.length > 0 ? id : null;
}

/** Старые URL `/gchat/gc1/` → редирект на `/gchat/?id=gc1` (static export). */
export function parseGChatLegacyPath(pathname: string): string | null {
  const path = norm(pathname);
  const m = path.match(/^\/gchat\/([^/]+)\/$/);
  if (!m) return null;
  return decodeURIComponent(m[1]);
}

export const routes = {
  home: () => "/",
  feed: () => "/feed/",
  chats: () => "/chats/",
  notes: () => "/notes/",
  analytics: () => "/analytics/",
  profile: () => "/profile/",
  login: () => "/login/",
  loginForgot: () => "/login/forgot/",
  register: () => "/register/",
  gchat: (id: string) => `/gchat/?${GCHAT_ID_PARAM}=${encodeURIComponent(id)}`,
  post: (id: string, chatId?: string | null) => {
    const base = `/post/${id}/`;
    if (chatId != null) return `${base}?chat=${chatId}`;
    return base;
  },
  /** Устаревшие подпути — только для редиректа в RouteSync. */
  postLegacySubPath: (id: string, sub: "comments" | "notes" | "chats") =>
    `/post/${id}/${sub}/`,
  noteNew: (from?: NoteFromScreen, postId?: string) => {
    const q = new URLSearchParams();
    if (from) q.set("from", from);
    if (postId != null) q.set("postId", postId);
    const qs = q.toString();
    return qs ? `/note/${NOTE_NEW_SLUG}/?${qs}` : `/note/${NOTE_NEW_SLUG}/`;
  },
  noteGlobal: (id: string) => `/note/global/${encodeURIComponent(id)}/`,
  notePost: (postId: string, noteId: string) => `/note/post/${postId}/${noteId}/`,
};

export function screenToHref(screen: ScreenId): string {
  switch (screen) {
    case "home":
      return routes.home();
    case "feed":
      return routes.feed();
    case "chats":
      return routes.chats();
    case "notes":
      return routes.notes();
    case "analytics":
      return routes.analytics();
    case "profile":
      return routes.profile();
    default:
      return routes.home();
  }
}

export function screenFromPath(pathname: string): ScreenId {
  return parseAppPath(pathname).screen;
}

export function isPostNewPath(pathname: string): boolean {
  return norm(pathname) === `/post/${POST_NEW_SLUG}/`;
}

export function getParentPath(pathname: string): string | null {
  const path = norm(pathname);
  if (path === "/") return null;

  if (isPostNewPath(path)) return routes.feed();

  const mPost = path.match(/^\/post\/([^/]+)\/$/);
  if (mPost) return routes.feed();

  if (path === "/gchat/" || path.startsWith("/gchat/")) return routes.chats();
  if (path.startsWith("/note/global/")) return routes.notes();
  if (path.match(/^\/note\/post\/[^/]+\/[^/]+\/$/)) {
    const parts = path.split("/").filter(Boolean);
    return routes.post(parts[2] ?? "");
  }
  if (path.startsWith(`/note/${NOTE_NEW_SLUG}/`)) return routes.notes();

  const top = [
    routes.feed(),
    routes.chats(),
    routes.notes(),
    routes.analytics(),
    routes.profile(),
  ];
  if (top.includes(path)) return routes.home();

  return null;
}

type RouteData = {
  posts: Post[];
  globalChats: GlobalChat[];
  globalNotes: GlobalNote[];
};

export function buildRoutePatch(
  parsed: ParsedAppPath,
  data: RouteData,
  noteFromFallback: NoteFromScreen = "notes",
): Partial<{
  screen: ScreenId;
  currentPostId: string | null;
  postMode: PostMode;
  isEditing: boolean;
  currentNote: ActiveNote | null;
  noteMode: "view" | "edit";
  noteFrom: NoteFromScreen;
  noteSavedSnapshot: string;
}> {
  const base = {
    screen: parsed.screen,
    isEditing: false,
    currentPostId: null as string | null,
    currentNote: null as ActiveNote | null,
  };

  if (parsed.screen === "gchat") {
    return { ...base };
  }

  if (parsed.screen === "post") {
    return {
      ...base,
      screen: "post",
      currentPostId: parsed.postId,
      postMode: parsed.postMode,
    };
  }

  if (parsed.screen === "note") {
    if (parsed.noteIsNew) {
      const fromPost = noteFromFallback === "post" && parsed.notePostId != null;
      const currentNote = fromPost
        ? createNewPostNote(parsed.notePostId!)
        : createNewGlobalNote();
      return {
        ...base,
        screen: "note",
        currentNote,
        noteMode: "edit",
        noteFrom: noteFromFallback,
        noteSavedSnapshot: EMPTY_NOTE_SNAPSHOT,
        ...(fromPost ? { currentPostId: parsed.notePostId } : {}),
      };
    }
    if (parsed.noteGlobalId) {
      const n = data.globalNotes.find((x) => x.id === parsed.noteGlobalId);
      if (!n) return { ...base, screen: "note", currentNote: null };
      const files = Array.isArray(n.files) ? n.files : [];
      return {
        ...base,
        screen: "note",
        currentNote: { ...n, isGlobal: true, files },
        noteFrom: "notes",
        noteMode: "view",
        noteSavedSnapshot: buildNoteSnapshot(n.title, n.body, n.ai, files),
      };
    }
    if (parsed.notePostId != null && parsed.noteId != null) {
      const post = data.posts.find((p) => p.id === parsed.notePostId);
      const n = post?.notes.find((x) => x.id === parsed.noteId);
      if (!n || !post) return { ...base, screen: "note", currentNote: null };
      const files = Array.isArray(n.files) ? n.files : [];
      return {
        ...base,
        screen: "note",
        currentPostId: parsed.notePostId,
        currentNote: { ...n, isGlobal: false, postId: parsed.notePostId, files },
        noteFrom: noteFromFallback,
        noteMode: "view",
        noteSavedSnapshot: buildNoteSnapshot(n.title, n.body, n.ai, files),
      };
    }
  }

  return base;
}

export function statePatchToHref(
  patch: Partial<{
    screen: ScreenId;
    currentPostId: string | null;
    postMode: PostMode;
    postChatId: string | null;
    gchatId: string | null;
    currentNote: ActiveNote | null;
    noteFrom: NoteFromScreen;
  }>,
  cur: { screen: ScreenId; currentPostId: string | null; postMode: PostMode },
): string | null {
  const screen = patch.screen ?? cur.screen;

  if (screen === "post") {
    const id = patch.currentPostId ?? cur.currentPostId;
    if (id == null) return routes.feed();
    return routes.post(id, patch.postChatId ?? null);
  }

  if (screen === "gchat" && patch.gchatId) {
    return routes.gchat(patch.gchatId);
  }

  if (screen === "note" && patch.currentNote) {
    const n = patch.currentNote;
    if (n.isNew) return routes.noteNew(patch.noteFrom);
    if (n.isGlobal && typeof n.id === "string") return routes.noteGlobal(n.id);
    if (!n.isGlobal && n.postId != null) return routes.notePost(n.postId, n.id);
  }

  if (screen === "note") return routes.noteNew(patch.noteFrom);

  return screenToHref(screen);
}

export function isPathActive(
  pathname: string,
  target: string,
  opts?: { exact?: boolean },
): boolean {
  const a = norm(pathname);
  const b = norm(target);
  if (opts?.exact) return a === b;
  return a === b || a.startsWith(b);
}

/** Dedup key for route sync and in-app navigation stack. */
export function routeSyncKey(pathname: string, searchParams: URLSearchParams): string {
  return `${pathname || "/"}?${searchParams.toString()}`;
}
