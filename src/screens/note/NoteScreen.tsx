"use client";

import { usePathname } from "next/navigation";
import { StickyNote } from "lucide-react";

import { useNoteFromRoute } from "@/screens/note/model/useNoteFromRoute";
import { useNoteScreen } from "@/screens/note/model/useNoteScreen";
import NoteBreadcrumb from "@/screens/note/ui/NoteBreadcrumb";
import NoteEditor from "@/screens/note/ui/NoteEditor";
import { EmptyState } from "@/shared/ui/empty-state";
import { PageHeader } from "@/widgets/page-header";

function NoteScreenPlaceholder({
  title,
  message,
  onBack,
}: {
  title: string;
  message: string;
  onBack: () => void;
}) {
  return (
    <div className="note-screen-wrap">
      <PageHeader title={title} onBack={onBack} />
      <div className="note-page">
        <EmptyState icon={<StickyNote className="size-5" />} message={message} className="min-h-[50vh]" />
      </div>
    </div>
  );
}

export function NoteScreen() {
  const pathname = usePathname() ?? "/";
  const { note, loading } = useNoteFromRoute(pathname);
  const { data, ui, actions } = useNoteScreen(note);

  if (loading) {
    return (
      <NoteScreenPlaceholder title="Заметка" message="Загрузка заметки…" onBack={actions.onBack} />
    );
  }

  if (!note) {
    return (
      <NoteScreenPlaceholder title="Заметка" message="Заметка не найдена." onBack={actions.onBack} />
    );
  }

  return (
    <div className="note-screen-wrap">
      <PageHeader
        onBack={actions.onBack}
        overflowItems={ui.noteHeaderMenuItems}
        left={
          <NoteBreadcrumb
            note={note}
            parentPost={data.parentPost}
            onNavigateNotes={actions.navigateNotes}
            onNavigateFeed={actions.navigateFeed}
            onOpenPost={actions.openPost}
          />
        }
      />
      <div className="note-page" id="note-page-body">
        <NoteEditor note={note} />
      </div>
    </div>
  );
}
