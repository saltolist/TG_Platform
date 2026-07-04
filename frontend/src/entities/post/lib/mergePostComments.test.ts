import { describe, expect, it } from "vitest";

import type { PostComment } from "@/shared/types";

import { mergePostCommentsFromServer, mergeCommentsWithDeleteTombstones } from "./mergePostComments";
import type { CommentDeleteTombstone } from "./mergePostComments";

const synced = {
  id: "1",
  author: "A",
  date: "2026-01-01T00:00:00.000Z",
  text: "synced",
  telegramMessageId: "100",
} as PostComment;

const pending = {
  id: "2",
  author: "Вы",
  date: "2026-01-02T00:00:00.000Z",
  text: "pending",
} as PostComment;

describe("mergePostCommentsFromServer", () => {
  it("returns server list when local is empty", () => {
    expect(mergePostCommentsFromServer([], [synced])).toEqual([synced]);
  });

  it("keeps local pending comments missing from a stale server snapshot", () => {
    expect(mergePostCommentsFromServer([synced, pending], [synced])).toEqual([synced, pending]);
  });

  it("prefers server data when the comment already exists remotely", () => {
    const localPending = { ...pending, text: "old draft" };
    const serverPending = { ...pending, text: "sent", telegramMessageId: "200" };
    expect(mergePostCommentsFromServer([localPending], [serverPending])).toEqual([serverPending]);
  });

  it("keeps self author when server returns a generic telegram label", () => {
    const localPending = { ...pending, text: "sent", telegramMessageId: "200" };
    const serverPending = {
      ...pending,
      author: "Пользователь",
      text: "sent",
      telegramMessageId: "200",
    };
    expect(mergePostCommentsFromServer([localPending], [serverPending])).toEqual([
      { ...serverPending, author: "Вы" },
    ]);
  });
});

describe("mergeCommentsWithDeleteTombstones", () => {
  it("keeps deleted comments in their original position until sync completes", () => {
    const middle = { ...synced, id: "2", text: "middle" };
    const last = { ...synced, id: "3", text: "last" };
    const tombstones = new Map<string, CommentDeleteTombstone>([
      ["2", { comment: middle, index: 1 }],
    ]);
    expect(mergeCommentsWithDeleteTombstones([synced, last], tombstones)).toEqual([
      synced,
      middle,
      last,
    ]);
  });

  it("keeps later tombstones in place while an earlier delete is still syncing", () => {
    const second = { ...synced, id: "2", text: "second" };
    const fourth = { ...synced, id: "4", text: "fourth" };
    const tombstones = new Map<string, CommentDeleteTombstone>([
      ["2", { comment: second, index: 1 }],
      ["4", { comment: fourth, index: 3 }],
    ]);
    const third = { ...synced, id: "3", text: "third" };
    expect(mergeCommentsWithDeleteTombstones([synced, third], tombstones)).toEqual([
      synced,
      second,
      third,
      fourth,
    ]);
  });
});
