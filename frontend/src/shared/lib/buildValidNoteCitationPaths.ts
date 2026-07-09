import { routes } from "@/shared/lib/routes";
import { normalizeNoteCitationPath } from "@/shared/lib/noteCitation";
import type { GlobalNote, Post } from "@/shared/types";

function postCitationTitle(post: Post): string {
  const firstLine = post.text.trim().split("\n")[0]?.trim() ?? "";
  if (firstLine) {
    return firstLine.length <= 72 ? firstLine : `${firstLine.slice(0, 69)}…`;
  }
  const rubric = post.rubric?.trim();
  if (rubric) return rubric;
  return "Пост";
}

/** Paths of notes and posts that exist in the current account (for filtering AI citation chips). */
export function buildValidNoteCitationPaths(
  globalNotes: GlobalNote[],
  posts: Post[],
): Set<string> {
  return new Set(buildNoteCitationTitlesByPath(globalNotes, posts).keys());
}

/** Canonical note/post titles keyed by normalized citation path. */
export function buildNoteCitationTitlesByPath(
  globalNotes: GlobalNote[],
  posts: Post[],
): Map<string, string> {
  const titles = new Map<string, string>();

  for (const note of globalNotes) {
    const path = normalizeNoteCitationPath(routes.noteGlobal(note.id));
    if (path) titles.set(path, (note.title || "Заметка").trim() || "Заметка");
  }

  for (const post of posts) {
    const path = normalizeNoteCitationPath(routes.post(post.id));
    if (path) titles.set(path, postCitationTitle(post));
    for (const note of post.notes ?? []) {
      const notePath = normalizeNoteCitationPath(routes.notePost(post.id, note.id));
      if (notePath) titles.set(notePath, (note.title || "Заметка").trim() || "Заметка");
    }
  }

  return titles;
}
