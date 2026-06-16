"use client";

import { NoteListCard } from "@/entities/note";
import { NoteListCardMenu } from "@/widgets/note-editor";
import { EmptyState } from "@/shared/ui/empty-state";
import { formatStoredDate } from "@/shared/lib/helpers";
import { matchesListContextFilter } from "@/shared/lib/listContextFilter";
import type { LocalNote, NoteListFilter, Post } from "@/shared/types";

type Props = {
  post: Post;
  search: string;
  contextFilter: NoteListFilter;
  onOpenNote: (note: LocalNote) => void;
  onToggleNoteAi: (noteId: string) => void;
};

export default function PostNotesList({
  post,
  search,
  contextFilter,
  onOpenNote,
  onToggleNoteAi,
}: Props) {
  const q = search.trim().toLowerCase();
  const notes = post.notes.filter((n) => {
    if (!matchesListContextFilter(n.ai, contextFilter)) return false;
    if (!q) return true;
    return n.title.toLowerCase().includes(q) || n.body.toLowerCase().includes(q);
  });

  return (
    <div id="post-notes" className="notes-grid notes-grid--screen visible">
      <div className="notes-grid-inner">
        {post.notes.length === 0 ? (
          <EmptyState icon="📝" message="Нет заметок для этого поста" />
        ) : notes.length === 0 ? (
          <EmptyState
            icon="📝"
            message={contextFilter === "all" ? "Ничего не найдено" : "Нет заметок по фильтру"}
          />
        ) : null}
        {notes.map((n) => (
          <NoteListCard
            key={n.id}
            title={n.title}
            body={n.body}
            meta={formatStoredDate(n.date)}
            ai={n.ai}
            onClick={() => onOpenNote(n)}
            onToggleAi={() => onToggleNoteAi(n.id)}
            menu={
              <NoteListCardMenu isGlobal={false} postId={post.id} noteId={n.id} title={n.title} />
            }
          />
        ))}
      </div>
    </div>
  );
}
