export type RecentRow =
  | {
      kind: "global";
      key: string;
      id: string;
      title: string;
      historyLen: number;
      seq: number;
    }
  | {
      kind: "local";
      key: string;
      postId: string;
      chatId: string;
      title: string;
      historyLen: number;
      seq: number;
    };

export type RecentChatsModel =
  | { mode: "flat"; rows: RecentRow[] }
  | { mode: "grouped"; thisPost: RecentRow[]; others: RecentRow[] };

export type RecentNoteRow =
  | {
      kind: "global";
      key: string;
      id: string;
      title: string;
      weight: number;
      seq: number;
    }
  | {
      kind: "local";
      key: string;
      postId: string;
      noteId: string;
      title: string;
      weight: number;
      seq: number;
    };

export type RecentNotesModel =
  | { mode: "flat"; rows: RecentNoteRow[] }
  | { mode: "grouped"; thisPost: RecentNoteRow[]; others: RecentNoteRow[] };

export const RECENT_SIDEBAR_MAX = 14;
export const RAIL_MIN_MQ = "(min-width: 761px)";
