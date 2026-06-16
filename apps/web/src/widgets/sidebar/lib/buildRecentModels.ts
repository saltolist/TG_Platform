import type { GlobalChat, GlobalNote, Post } from "@/shared/types";
import {
  RECENT_SIDEBAR_MAX,
  type RecentChatsModel,
  type RecentNoteRow,
  type RecentNotesModel,
  type RecentRow,
} from "@/widgets/sidebar/model/types";

export type SidebarData = {
  posts: Post[];
  globalChats: GlobalChat[];
  globalNotes: GlobalNote[];
};

const byChatActivity = (a: RecentRow, b: RecentRow) =>
  b.historyLen - a.historyLen || a.seq - b.seq;

const noteWeight = (body: string) => body?.length ?? 0;

const byNoteActivity = (a: RecentNoteRow, b: RecentNoteRow) =>
  b.weight - a.weight || a.seq - b.seq;

export function buildRecentChatsModel(
  data: SidebarData,
  sidebarPostId: string | null,
): RecentChatsModel {
  const globalRows: RecentRow[] = [];
  let gSeq = 0;
  for (const c of data.globalChats) {
    globalRows.push({
      kind: "global",
      key: `g:${c.id}`,
      id: c.id,
      title: c.title || "Без названия",
      historyLen: c.history.length,
      seq: gSeq++,
    });
  }
  globalRows.sort(byChatActivity);

  const inPostSpace =
    sidebarPostId != null && data.posts.some((p) => p.id === sidebarPostId);

  if (!inPostSpace) {
    const allLocal: RecentRow[] = [];
    let seq = 0;
    for (const p of data.posts) {
      for (const c of p.chats) {
        allLocal.push({
          kind: "local",
          key: `l:${p.id}-${c.id}`,
          postId: p.id,
          chatId: c.id,
          title: c.title || "Без названия",
          historyLen: c.history.length,
          seq: seq++,
        });
      }
    }
    const mixed = [...globalRows, ...allLocal];
    mixed.sort(byChatActivity);
    return { mode: "flat", rows: mixed.slice(0, RECENT_SIDEBAR_MAX) };
  }

  const post = data.posts.find((p) => p.id === sidebarPostId)!;
  const thisPostRows: RecentRow[] = [];
  let tpSeq = 0;
  for (const c of post.chats) {
    thisPostRows.push({
      kind: "local",
      key: `l:${post.id}-${c.id}`,
      postId: post.id,
      chatId: c.id,
      title: c.title || "Без названия",
      historyLen: c.history.length,
      seq: tpSeq++,
    });
  }
  thisPostRows.sort(byChatActivity);

  const othersRows: RecentRow[] = [];
  let oSeq = 0;
  for (const c of data.globalChats) {
    othersRows.push({
      kind: "global",
      key: `g:${c.id}`,
      id: c.id,
      title: c.title || "Без названия",
      historyLen: c.history.length,
      seq: oSeq++,
    });
  }
  for (const p of data.posts) {
    if (p.id === post.id) continue;
    for (const c of p.chats) {
      othersRows.push({
        kind: "local",
        key: `l:${p.id}-${c.id}`,
        postId: p.id,
        chatId: c.id,
        title: c.title || "Без названия",
        historyLen: c.history.length,
        seq: oSeq++,
      });
    }
  }
  othersRows.sort(byChatActivity);

  const thisPost = thisPostRows.slice(0, RECENT_SIDEBAR_MAX);
  const others = othersRows.slice(0, Math.max(0, RECENT_SIDEBAR_MAX - thisPost.length));

  return { mode: "grouped", thisPost, others };
}

export function buildRecentNotesModel(
  data: SidebarData,
  sidebarPostId: string | null,
): RecentNotesModel {
  const globalRows: RecentNoteRow[] = [];
  let gSeq = 0;
  for (const n of data.globalNotes) {
    globalRows.push({
      kind: "global",
      key: `ng:${n.id}`,
      id: n.id,
      title: n.title || "Без названия",
      weight: noteWeight(n.body),
      seq: gSeq++,
    });
  }
  globalRows.sort(byNoteActivity);

  const inPostSpace =
    sidebarPostId != null && data.posts.some((p) => p.id === sidebarPostId);

  if (!inPostSpace) {
    const allLocal: RecentNoteRow[] = [];
    let seq = 0;
    for (const p of data.posts) {
      for (const n of p.notes) {
        allLocal.push({
          kind: "local",
          key: `nl:${p.id}-${n.id}`,
          postId: p.id,
          noteId: n.id,
          title: n.title || "Без названия",
          weight: noteWeight(n.body),
          seq: seq++,
        });
      }
    }
    const mixed = [...globalRows, ...allLocal];
    mixed.sort(byNoteActivity);
    return { mode: "flat", rows: mixed.slice(0, RECENT_SIDEBAR_MAX) };
  }

  const post = data.posts.find((p) => p.id === sidebarPostId)!;
  const thisPostRows: RecentNoteRow[] = [];
  let tpSeq = 0;
  for (const n of post.notes) {
    thisPostRows.push({
      kind: "local",
      key: `nl:${post.id}-${n.id}`,
      postId: post.id,
      noteId: n.id,
      title: n.title || "Без названия",
      weight: noteWeight(n.body),
      seq: tpSeq++,
    });
  }
  thisPostRows.sort(byNoteActivity);

  const othersRows: RecentNoteRow[] = [];
  let oSeq = 0;
  for (const n of data.globalNotes) {
    othersRows.push({
      kind: "global",
      key: `ng:${n.id}`,
      id: n.id,
      title: n.title || "Без названия",
      weight: noteWeight(n.body),
      seq: oSeq++,
    });
  }
  for (const p of data.posts) {
    if (p.id === post.id) continue;
    for (const n of p.notes) {
      othersRows.push({
        kind: "local",
        key: `nl:${p.id}-${n.id}`,
        postId: p.id,
        noteId: n.id,
        title: n.title || "Без названия",
        weight: noteWeight(n.body),
        seq: oSeq++,
      });
    }
  }
  othersRows.sort(byNoteActivity);

  const thisPost = thisPostRows.slice(0, RECENT_SIDEBAR_MAX);
  const others = othersRows.slice(0, Math.max(0, RECENT_SIDEBAR_MAX - thisPost.length));

  return { mode: "grouped", thisPost, others };
}
