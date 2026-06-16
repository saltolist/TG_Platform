"use client";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { buildListContextFilterTabs } from "@/shared/lib/listContextFilter";
import { FilterToolbar, FilterToolbarAction } from "@/widgets/filter-toolbar";
import { type PostWorkspace } from "@/widgets/post-workspace";
import PostNotesList from "@/screens/post/ui/PostNotesList";
import type { Post } from "@/shared/types";

type Props = {
  post: Post;
  ui: Pick<PostWorkspace["ui"], "listSearch" | "listContextFilter" | "setListContextFilter">;
  actions: Pick<PostWorkspace["actions"], "startNewNote" | "openNote" | "toggleNoteAi">;
};

export default function PostNotesView({ post, ui, actions }: Props) {
  const isMobile = useMobile760();
  const { listSearch, listContextFilter, setListContextFilter } = ui;
  const { startNewNote, openNote, toggleNoteAi } = actions;

  return (
    <div className="post-subpage-scroll">
      <FilterToolbar
        className="post-subpage-toolbar"
        width="composer"
        tabs={buildListContextFilterTabs(true)}
        mobileTabs={buildListContextFilterTabs(false)}
        value={listContextFilter}
        onChange={setListContextFilter}
        selectClassName="notes-filter-tab-select"
        tabAriaLabel="Фильтр заметок"
        action={
          <FilterToolbarAction
            label="Новая заметка"
            onClick={startNewNote}
            className={`notes-new-note-btn${isMobile ? " filter-tab--dropdown" : ""}`}
            iconClassName="notes-new-note-btn-icon"
          />
        }
      />
      <PostNotesList
        post={post}
        search={listSearch}
        contextFilter={listContextFilter}
        onOpenNote={openNote}
        onToggleNoteAi={toggleNoteAi}
      />
    </div>
  );
}
