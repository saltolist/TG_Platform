import { routes } from "@/shared/lib/routes";
import { normalizeNoteCitationPath } from "@/shared/lib/noteCitation";
import type { GlobalNote, Post } from "@/shared/types";

/** Paths of notes that exist in the current account (for filtering AI citation chips). */
export function buildValidNoteCitationPaths(
  globalNotes: GlobalNote[],
  posts: Post[],
): Set<string> {
  const paths = new Set<string>();

  for (const note of globalNotes) {
    const path = normalizeNoteCitationPath(routes.noteGlobal(note.id));
    if (path) paths.add(path);
  }

  for (const post of posts) {
    for (const note of post.notes ?? []) {
      const path = normalizeNoteCitationPath(routes.notePost(post.id, note.id));
      if (path) paths.add(path);
    }
  }

  return paths;
}
