import { matchesListContextFilter } from "@/shared/lib/listContextFilter";
import { postTitle } from "@/shared/lib/helpers";
import type { GlobalNote, LocalNote, NoteListFilter, NoteScope, Post } from "@/shared/types";

export type AnyNote =
  | (GlobalNote & { isGlobal: true })
  | (LocalNote & { isGlobal: false; postId: string; postTitle: string });

export function normalizeNoteSearchQuery(query: string): string {
  return query.trim().toLowerCase();
}

export function noteMatchesSearch(
  note: Pick<AnyNote, "title" | "body">,
  query: string,
): boolean {
  const q = normalizeNoteSearchQuery(query);
  if (!q) return true;
  return note.title.toLowerCase().includes(q) || note.body.toLowerCase().includes(q);
}

export function buildAnyNoteItems(globalNotes: GlobalNote[], posts: Post[]): AnyNote[] {
  const globalItems: AnyNote[] = globalNotes.map((n) => ({ ...n, isGlobal: true }));
  const localItems: AnyNote[] = posts.flatMap((p) =>
    p.notes.map((n) => ({
      ...n,
      isGlobal: false as const,
      postId: p.id,
      postTitle: postTitle(p),
    })),
  );
  return [...globalItems, ...localItems];
}

export function filterNotesByScope(items: AnyNote[], scope: NoteScope): AnyNote[] {
  if (scope === "global") return items.filter((n) => n.isGlobal);
  if (scope === "local") return items.filter((n) => !n.isGlobal);
  return items;
}

export function filterAnyNotes(
  items: AnyNote[],
  options: { filter: NoteListFilter; searchQuery?: string },
): AnyNote[] {
  const { filter, searchQuery = "" } = options;
  return items.filter(
    (n) => matchesListContextFilter(n.ai, filter) && noteMatchesSearch(n, searchQuery),
  );
}

export function notesEmptyLabel(scope: NoteScope): string {
  if (scope === "global") return "Нет глобальных заметок";
  if (scope === "local") return "Нет локальных заметок";
  return "Нет заметок";
}
