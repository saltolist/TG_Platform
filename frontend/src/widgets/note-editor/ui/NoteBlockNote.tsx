"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { filterSuggestionItems } from "@blocknote/core/extensions";
import { ru } from "@blocknote/core/locales";
import { BlockNoteView } from "@blocknote/mantine";
import {
  getDefaultReactSlashMenuItems,
  SuggestionMenuController,
  useCreateBlockNote,
} from "@blocknote/react";
import { useTheme } from "next-themes";

import "@blocknote/core/fonts/inter.css";
import "@blocknote/mantine/style.css";

import type { NoteFile } from "@/shared/types";
import { ATTACHMENT_PREFIX, restoreUrlsToAttachments } from "@/widgets/note-editor/lib/noteMarkdownBridge";
import { restoreDocAttachments } from "@/widgets/note-editor/lib/noteDocAttachments";
import { useNoteBlockDragCleanup } from "@/widgets/note-editor/lib/noteDragCleanup";
import { loadNoteContentIntoEditor } from "@/widgets/note-editor/lib/loadNoteContent";
import { useSafariNoteEditorFixes } from "@/widgets/note-editor/lib/noteSafariFixes";

export type NoteBlockNoteChange = { doc: unknown[]; body: string };

type Props = {
  doc?: unknown[];
  body: string;
  files: NoteFile[];
  getFiles: () => NoteFile[];
  onChange: (content: NoteBlockNoteChange) => void;
  onUploadFile: (file: File) => Promise<NoteFile>;
  focusRequest?: number;
};

/** BlockNote body: `doc` is source of truth; `body` is derived markdown for RAG. */
export default function NoteBlockNote({
  doc,
  body,
  files,
  getFiles,
  onChange,
  onUploadFile,
  focusRequest = 0,
}: Props) {
  const { resolvedTheme } = useTheme();

  const getFilesRef = useRef(getFiles);
  getFilesRef.current = getFiles;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onUploadRef = useRef(onUploadFile);
  onUploadRef.current = onUploadFile;

  const editor = useCreateBlockNote({
    trailingBlock: false,
    dictionary: ru,
    uploadFile: async (file: File) => {
      const entry = await onUploadRef.current(file);
      return entry.url ?? `${ATTACHMENT_PREFIX}${entry.id ?? entry.name}`;
    },
  });

  useSafariNoteEditorFixes(editor);
  useNoteBlockDragCleanup(editor);

  const getSlashMenuItems = useMemo(
    () => async (query: string) =>
      filterSuggestionItems(getDefaultReactSlashMenuItems(editor), query),
    [editor],
  );

  const acceptingChangesRef = useRef(false);
  const initialContentRef = useRef({ doc, body, files });
  const filesReadyRef = useRef(files.length > 0);

  useEffect(() => {
    acceptingChangesRef.current = false;
    loadNoteContentIntoEditor(editor, initialContentRef.current);

    const id = window.setTimeout(() => {
      acceptingChangesRef.current = true;
    }, 0);
    return () => window.clearTimeout(id);
  }, [editor]);

  useEffect(() => {
    if (filesReadyRef.current || files.length === 0) return;
    filesReadyRef.current = true;

    acceptingChangesRef.current = false;
    loadNoteContentIntoEditor(editor, { ...initialContentRef.current, files });
    const id = window.setTimeout(() => {
      acceptingChangesRef.current = true;
    }, 0);
    return () => window.clearTimeout(id);
  }, [editor, files]);

  const emit = useCallback(() => {
    const currentFiles = getFilesRef.current();
    const docOut = restoreDocAttachments(editor.document as unknown[], currentFiles);
    const bodyOut = restoreUrlsToAttachments(
      editor.blocksToMarkdownLossy(editor.document),
      currentFiles,
    ).trimEnd();
    onChangeRef.current({ doc: docOut, body: bodyOut });
  }, [editor]);

  const handleChange = useCallback(() => {
    if (!acceptingChangesRef.current) return;
    emit();
  }, [emit]);

  const handledFocusRef = useRef(0);
  useEffect(() => {
    if (focusRequest <= handledFocusRef.current) return;
    handledFocusRef.current = focusRequest;
    editor.focus();
  }, [editor, focusRequest]);

  return (
    <BlockNoteView
      editor={editor}
      theme={resolvedTheme === "dark" ? "dark" : "light"}
      slashMenu={false}
      onChange={handleChange}
    >
      <SuggestionMenuController triggerCharacter="/" getItems={getSlashMenuItems} />
    </BlockNoteView>
  );
}
