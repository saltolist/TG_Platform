"use client";

import { useRouter } from "next/navigation";

import { useNavigationStore } from "@/app/model/store";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { routes } from "@/shared/lib/routes";
import type { NoteListFilter } from "@/shared/types";
import {
  FilterToolbar,
  FilterToolbarAction,
  NotesScopeFilterSelect,
} from "@/widgets/filter-toolbar";

const FILTER_TABS: { value: NoteListFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "ai", label: "В контексте ИИ" },
  { value: "noai", label: "Не в контексте ИИ" },
];

export function NotesFilterRow() {
  const router = useRouter();
  const isMobile = useMobile760();
  const scope = useNavigationStore((s) => s.noteScope);
  const filter = useNavigationStore((s) => s.noteFilter);
  const setNoteScope = useNavigationStore((s) => s.setNoteScope);
  const setNoteFilter = useNavigationStore((s) => s.setNoteFilter);

  return (
    <FilterToolbar
      className="notes-filter-row"
      width="content"
      tabs={FILTER_TABS}
      value={filter}
      onChange={setNoteFilter}
      mobileFilter={<NotesScopeFilterSelect value={scope} onChange={setNoteScope} />}
      selectClassName="notes-filter-tab-select"
      tabAriaLabel="Фильтр заметок"
      action={
        scope === "global" || scope === "all" ? (
          <FilterToolbarAction
            label="Новая заметка"
            onClick={() => router.push(routes.noteNew("notes"))}
            className={`notes-new-note-btn${isMobile ? " filter-tab--dropdown" : ""}`}
            iconClassName="notes-new-note-btn-icon"
          />
        ) : null
      }
    />
  );
}
