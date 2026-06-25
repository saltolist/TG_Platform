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
  const setNav = useNavigationStore((s) => s.setNav);
  const setNoteDirty = useUiStore((s) => s.setNoteDirty);
  const upsertGlobalNote = useUpsertGlobalNote();
  const addPostNote = useAddPostNote();
  const updatePostNote = useUpdatePostNote();
  const isMobile = useMobile760();
  const noteKey = noteIdentityKey(note);

  const patchNote = useCallback(
    (patch: NavigationPatch) => {
      setNav(patch);
    },
    [setNav],
  );

  const noteFiles = useMemo(() => (Array.isArray(note.files) ? note.files : []), [note.files]);
  const initialBody = note.body ?? "";
  const initialDoc = Array.isArray(note.doc) ? note.doc : undefined;
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(initialBody);
  const [doc, setDoc] = useState<unknown[] | undefined>(initialDoc);
  const [files, setFiles] = useState<NoteFile[]>([...noteFiles]);
  const [bodyFocusRequest, setBodyFocusRequest] = useState(0);
  const [editorResetKey, setEditorResetKey] = useState(0);
  const [baselineSnapshot, setBaselineSnapshot] = useState(() =>
    buildNoteSnapshot(note.title, initialBody, note.ai, noteFiles, initialDoc),
  );

  const titleRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const nextFiles = Array.isArray(note.files) ? [...note.files] : [];
    const nextBody = note.body ?? "";
    setTitle(note.title);
    setBody(nextBody);
    setDoc(Array.isArray(note.doc) ? note.doc : undefined);
    setFiles(nextFiles);
    setEditorResetKey(0);
    setBaselineSnapshot(buildNoteSnapshot(note.title, nextBody, note.ai, nextFiles, Array.isArray(note.doc) ? note.doc : undefined));
  }, [noteKey]); // eslint-disable-line react-hooks/exhaustive-deps -- reset draft only when note identity changes

  useEffect(() => {
    setBaselineSnapshot((prev) => patchNoteSnapshotAi(prev, note.ai));
  }, [note.ai]);

  const changed = useMemo(
    () => buildNoteSnapshot(title, body, note.ai, files, doc) !== baselineSnapshot,
    [title, body, note.ai, files, doc, baselineSnapshot],
  );

  useEffect(() => {
    setNoteDirty(changed);
  }, [changed, setNoteDirty]);

  useFitTitleSize(titleRef, title, true);
  usePreventIosInputZoom(titleRef, isMobile);

  const cancel = useCallback(() => {
    const nextBody = note.body ?? "";
    const nextFiles = [...noteFiles];
    setTitle(note.title);
    setBody(nextBody);
    setDoc(Array.isArray(note.doc) ? note.doc : undefined);
    setFiles(nextFiles);
    setEditorResetKey((key) => key + 1);
    setBaselineSnapshot(buildNoteSnapshot(note.title, nextBody, note.ai, nextFiles, Array.isArray(note.doc) ? note.doc : undefined));
    setNoteDirty(false);
  }, [note, noteFiles, setNoteDirty]);

  const setContent = useCallback((content: { doc: unknown[]; body: string }) => {
    setDoc(content.doc);
    setBody(content.body);
  }, []);

  const save = useCallback(async () => {
    const finalTitle = draftNoteTitle(title);
    const snapshot = buildNoteSnapshot(finalTitle, body, note.ai, files, doc);
    if (snapshot === baselineSnapshot) return;

    try {
      if (note.isNew) {
        if (note.isGlobal) {
          const saved = {
            id: randomId(),
            title: finalTitle,
            body,
            doc,
            ai: note.ai,
            date: new Date().toISOString(),
            files,
          };
          await upsertGlobalNote.mutateAsync(saved);
          patchNote({
            currentNote: { ...saved, isGlobal: true, files },
            noteMode: "view",
            noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files, doc),
          });
        } else {
          const saved = {
            id: randomId(),
            title: finalTitle,
            body,
            doc,
            ai: note.ai,
            date: new Date().toISOString(),
            files,
          };
          await addPostNote(note.postId, saved);
          patchNote({
            currentNote: { ...saved, isGlobal: false, postId: note.postId, files },
            noteMode: "view",
            noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files, doc),
          });
        }
        setBaselineSnapshot(snapshot);
        setNoteDirty(false);
        return;
      }

      if (note.isGlobal) {
        const next = {
          id: note.id,
          title: finalTitle,
          body,
          doc,
          ai: note.ai,
          date: note.date,
          files,
        };
        await upsertGlobalNote.mutateAsync(next);
        patchNote({
          currentNote: { ...next, isGlobal: true, files },
          noteMode: "view",
          noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files, doc),
        });
      } else {
        await updatePostNote(note.postId, note.id, { title: finalTitle, body, doc, files });
        patchNote({
          currentNote: { ...note, title: finalTitle, body, doc, files },
          noteMode: "view",
          noteSavedSnapshot: buildNoteSnapshot(finalTitle, body, note.ai, files, doc),
        });
      }
      setBaselineSnapshot(snapshot);
      setNoteDirty(false);
    } catch (error) {
      console.error("Failed to save note", error);
    }
  }, [
    addPostNote,
    baselineSnapshot,
    body,
    doc,
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
      id: randomId(),
      name: file.name,
      type: file.type || "file",
      url: URL.createObjectURL(file),
    };
    setFiles((arr) => [...arr, entry]);
    return entry;
  }, []);

  const focusBodyFromTitle = useCallback(() => {
    setBodyFocusRequest((request) => request + 1);
  }, []);

  return {
    note,
    title,
    setTitle,
    body,
    setBody,
    doc,
    setContent,
    files,
    changed,
    bodyFocusRequest,
    editorResetKey,
    titleRef,
    save,
    cancel,
    addFile,
    focusBodyFromTitle,
  };
}

export type NoteEditorState = ReturnType<typeof useNoteEditor>;
