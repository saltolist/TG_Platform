"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useUiStore } from "@/app/model/store";
import { useNavigationStore } from "@/app/model/store/navigation-store";
import type { NavigationPatch } from "@/app/model/store/navigation/types";
import {
  useAddPostNote,
  useUpdatePostNote,
} from "@/entities/post/model/usePostNoteMutations";
import { useUpsertGlobalNote } from "@/entities/note";
import { randomId } from "@/shared/lib/randomId";
import { normalizeNoteBody } from "@/shared/lib/noteEmbeds";
import {
  buildNoteSnapshot,
  draftNoteTitle,
  noteIdentityKey,
  patchNoteSnapshotAi,
} from "@/shared/lib/noteDraft";
import { usePreventIosInputZoom } from "@/shared/lib/hooks/usePreventIosInputZoom";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { registerNotePersist } from "@/shared/lib/notePersistRegistry";
import { useFitTitleSize } from "@/shared/lib/use-fit-title";
import type { ActiveNote, NoteFile } from "@/shared/types";

export function useNoteEditor(note: ActiveNote) {
  const noteMode = useNavigationStore((s) => s.noteMode);
  const setNav = useNavigationStore((s) => s.setNav);
  const setNoteDirty = useUiStore((s) => s.setNoteDirty);
  const upsertGlobalNote = useUpsertGlobalNote();
  const addPostNote = useAddPostNote();
  const updatePostNote = useUpdatePostNote();
  const isMobile = useMobile760();
  const noteKey = noteIdentityKey(note);
  const isView = noteMode === "view";

  const patchNote = useCallback(
    (patch: NavigationPatch) => {
      setNav(patch);
    },
    [setNav],
  );

  const noteFiles = useMemo(() => (Array.isArray(note.files) ? note.files : []), [note.files]);
  const initialBody = normalizeNoteBody(note.body, noteFiles);
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(initialBody);
  const [files, setFiles] = useState<NoteFile[]>([...noteFiles]);
  const [bodyFocusRequest, setBodyFocusRequest] = useState(0);
  const [baselineSnapshot, setBaselineSnapshot] = useState(() =>
    buildNoteSnapshot(note.title, initialBody, note.ai, noteFiles),
  );

  const titleRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const nextFiles = Array.isArray(note.files) ? [...note.files] : [];
    const nextBody = normalizeNoteBody(note.body, nextFiles);
    setTitle(note.title);
    setBody(nextBody);
    setFiles(nextFiles);
    setBaselineSnapshot(buildNoteSnapshot(note.title, nextBody, note.ai, nextFiles));
  }, [noteKey]); // eslint-disable-line react-hooks/exhaustive-deps -- reset draft only when note identity changes

  useEffect(() => {
    setBaselineSnapshot((prev) => patchNoteSnapshotAi(prev, note.ai));
  }, [note.ai]);

  const changed = useMemo(
    () => buildNoteSnapshot(title, body, note.ai, files) !== baselineSnapshot,
    [title, body, note.ai, files, baselineSnapshot],
  );

  useEffect(() => {
    setNoteDirty(changed);
  }, [changed, setNoteDirty]);

  useFitTitleSize(titleRef, title, true);
  usePreventIosInputZoom(titleRef, isMobile);

  const setViewMode = useCallback(() => {
    patchNote({ noteMode: "view" });
  }, [patchNote]);

  const setEditMode = useCallback(() => {
    patchNote({ noteMode: "edit" });
  }, [patchNote]);

  const cancel = useCallback(() => {
    const nextBody = normalizeNoteBody(note.body, noteFiles);
    const nextFiles = [...noteFiles];
    setTitle(note.title);
    setBody(nextBody);
    setFiles(nextFiles);
    setBaselineSnapshot(buildNoteSnapshot(note.title, nextBody, note.ai, nextFiles));
    setNoteDirty(false);
  }, [note, noteFiles, setNoteDirty]);

  const save = useCallback(() => {
    const finalTitle = draftNoteTitle(title);
    const snapshot = buildNoteSnapshot(finalTitle, body, note.ai, files);
    if (snapshot === baselineSnapshot) return;

    if (note.isNew) {
      if (note.isGlobal) {
        const saved = {
          id: randomId(),
          title: finalTitle,
          body,
          ai: note.ai,
          date: new Date().toISOString(),
          files,
        };
        void upsertGlobalNote.mutateAsync(saved);
        patchNote({
          currentNote: { ...saved, isGlobal: true, files },
          noteMode: "view",
          noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files),
        });
      } else {
        const saved = {
          id: randomId(),
          title: finalTitle,
          body,
          ai: note.ai,
          date: new Date().toISOString(),
          files,
        };
        void addPostNote(note.postId, saved);
        patchNote({
          currentNote: { ...saved, isGlobal: false, postId: note.postId, files },
          noteMode: "view",
          noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files),
        });
      }
      setBaselineSnapshot(snapshot);
      setNoteDirty(false);
      return;
    }

    if (note.isGlobal) {
      const next = { id: note.id, title: finalTitle, body, ai: note.ai, date: note.date, files };
      void upsertGlobalNote.mutateAsync(next);
      patchNote({
        currentNote: { ...next, isGlobal: true, files },
        noteMode: "view",
        noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files),
      });
    } else {
      void updatePostNote(note.postId, note.id, { title: finalTitle, body, files });
      patchNote({
        currentNote: { ...note, title: finalTitle, body, files },
        noteMode: "view",
        noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files),
      });
    }
    setBaselineSnapshot(snapshot);
    setNoteDirty(false);
  }, [
    addPostNote,
    baselineSnapshot,
    body,
    files,
    note,
    patchNote,
    setNoteDirty,
    title,
    updatePostNote,
    upsertGlobalNote,
  ]);

  useEffect(() => {
    registerNotePersist(save);
    return () => registerNotePersist(null);
  }, [save]);

  const addFile = useCallback((file: File) => {
    const entry: NoteFile = {
      name: file.name,
      type: file.type || "file",
      url: URL.createObjectURL(file),
    };
    setFiles((arr) => [...arr, entry]);
    return entry;
  }, []);

  const onFilePicked = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      addFile(file);
      e.target.value = "";
    },
    [addFile],
  );

  const focusBodyFromTitle = useCallback(() => {
    if (isView) setEditMode();
    setBodyFocusRequest((request) => request + 1);
  }, [isView, setEditMode]);

  return {
    note,
    title,
    setTitle,
    body,
    setBody,
    files,
    isView,
    changed,
    bodyFocusRequest,
    titleRef,
    fileInputRef,
    setEditMode,
    setViewMode,
    save,
    cancel,
    addFile,
    onFilePicked,
    focusBodyFromTitle,
  };
}

export type NoteEditorState = ReturnType<typeof useNoteEditor>;
