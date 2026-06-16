"use client";

import { useCallback } from "react";

import { useGlobalNotes, useUpsertGlobalNote } from "@/entities/note";
import { useUpdatePostNote } from "@/entities/post/model/usePostNoteMutations";

type GlobalTarget = { isGlobal: true; noteId: string };
type LocalTarget = { isGlobal: false; postId: string; noteId: string };

export function useRenameNote() {
  const { data: globalNotes = [] } = useGlobalNotes();
  const upsertGlobalNote = useUpsertGlobalNote();
  const updatePostNote = useUpdatePostNote();

  return useCallback(
    (target: GlobalTarget | LocalTarget, title: string) => {
      const next = window.prompt("Новое название заметки", title);
      if (next == null) return;
      const t = next.trim();
      if (!t) return;
      if (target.isGlobal) {
        const n = globalNotes.find((x) => x.id === target.noteId);
        if (!n) return;
        void upsertGlobalNote.mutateAsync({ ...n, title: t });
      } else {
        void updatePostNote(target.postId, target.noteId, { title: t });
      }
    },
    [globalNotes, updatePostNote, upsertGlobalNote],
  );
}
