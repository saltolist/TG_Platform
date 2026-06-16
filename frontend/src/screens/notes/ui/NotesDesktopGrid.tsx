"use client";

import { NoteCardAiToggle } from "@/entities/note";
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

export function NotesDesktopGrid({
  notes,
  emptyLabel,
  showConnectChannel = false,
  onOpen,
  onToggleAi,
}: Props) {
  return (
    <div className="notes-grid-layout">
      {notes.length === 0 ? (
        showConnectChannel ? (
          <ConnectChannelEmptyState feature="заметкам" icon="📝" className="empty" />
        ) : (
          <EmptyState icon="📝" message={emptyLabel} className="empty" />
        )
      ) : (
        notes.map((n) => (
          <div
            key={`${n.isGlobal ? "g" : `l-${n.postId}`}-${n.id}`}
            className="note-card-page"
            onClick={() => onOpen(n)}
          >
            <div className="note-card-page-head">
              <div className="note-card-name">{n.title}</div>
              <div className="chat-card-menu-slot" onClick={(e) => e.stopPropagation()}>
                {n.isGlobal ? (
                  <NoteListCardMenu isGlobal noteId={n.id} title={n.title} />
                ) : (
                  <NoteListCardMenu
                    isGlobal={false}
                    postId={n.postId}
                    noteId={n.id}
                    title={n.title}
                  />
                )}
              </div>
            </div>
            <div className="note-card-preview">{n.body}</div>
            <div className="note-card-footer-pg">
              <div className="note-card-footer-start">
                <NoteCardAiToggle ai={n.ai} onClick={() => onToggleAi(n)} />
              </div>
              <span className="note-card-meta-pg">
                {formatStoredDate(n.date)} · {n.isGlobal ? "Глобальная" : "Локальная"}
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
