"use client";

import { NoteListCard } from "@/entities/note";
import { formatStoredDate } from "@/shared/lib/helpers";
import type { AnyNote } from "@/shared/lib/notes/noteList";
import { ConnectChannelEmptyState } from "@/features/connect-channel";
import { EmptyState } from "@/shared/ui/empty-state";
import { NoteListCardMenu } from "@/widgets/note-editor";

type Props = {
  notes: AnyNote[];
  emptyLabel: string;
  showConnectChannel?: boolean;
  onOpen: (n: AnyNote) => void;
  onToggleAi: (n: AnyNote) => void;
};

export function NotesMobileGrid({
  notes,
  emptyLabel,
  showConnectChannel = false,
  onOpen,
  onToggleAi,
}: Props) {
  return (
    <div className="notes-grid notes-grid--screen visible">
      <div className="notes-grid-inner">
        {notes.length === 0 ? (
          showConnectChannel ? (
            <ConnectChannelEmptyState feature="заметкам" icon="📝" />
          ) : (
            <EmptyState icon="📝" message={emptyLabel} />
          )
        ) : (
          notes.map((n) => (
            <NoteListCard
              key={`${n.isGlobal ? "g" : `l-${n.postId}`}-${n.id}`}
              title={n.title}
              body={n.body}
              meta={`${formatStoredDate(n.date)} · ${n.isGlobal ? "Глобальная" : "Локальная"}`}
              ai={n.ai}
              onClick={() => onOpen(n)}
              onToggleAi={() => onToggleAi(n)}
              menu={
                n.isGlobal ? (
                  <NoteListCardMenu isGlobal noteId={n.id} title={n.title} />
                ) : (
                  <NoteListCardMenu
                    isGlobal={false}
                    postId={n.postId}
                    noteId={n.id}
                    title={n.title}
                  />
                )
              }
            />
          ))
        )}
      </div>
    </div>
  );
}
