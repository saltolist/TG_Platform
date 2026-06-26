"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import type { PartialBlock } from "@blocknote/core";
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
import {
  ATTACHMENT_PREFIX,
  resolveAttachmentsToUrls,
  restoreUrlsToAttachments,
} from "@/widgets/note-editor/lib/noteMarkdownBridge";
import {
  resolveDocAttachments,
  restoreDocAttachments,
} from "@/widgets/note-editor/lib/noteDocAttachments";
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

  const initialContent = useMemo((): PartialBlock[] | undefined => {
    if (doc && doc.length > 0) {
      return resolveDocAttachments(doc, files) as PartialBlock[];
    }
    return undefined;
  }, [doc, files]);

  const editor = useCreateBlockNote({
    initialContent,
    trailingBlock: false,
    dictionary: ru,
    uploadFile: async (file: File) => {
      const entry = await onUploadRef.current(file);
      return entry.url ?? `${ATTACHMENT_PREFIX}${entry.id ?? entry.name}`;
    },
  });

  useSafariNoteEditorFixes(editor);

  const getSlashMenuItems = useMemo(
    () => async (query: string) =>
      filterSuggestionItems(getDefaultReactSlashMenuItems(editor), query),
    [editor],
  );

  const acceptingChangesRef = useRef(false);

  // Legacy notes stored as markdown only (no `doc` yet).
  useEffect(() => {
    acceptingChangesRef.current = false;
    if (!initialContent && body.trim()) {
      try {
        const markdown = resolveAttachmentsToUrls(body, getFilesRef.current());
        const blocks = editor.tryParseMarkdownToBlocks(markdown);
        if (blocks.length > 0) editor.replaceBlocks(editor.document, blocks);
      } catch {
        // keep default empty document
      }
    }
    const id = window.setTimeout(() => {
      acceptingChangesRef.current = true;
    }, 0);
    return () => window.clearTimeout(id);
  }, [body, editor, initialContent]);

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
