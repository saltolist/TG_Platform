"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { BlockNoteSchema, combineByGroup } from "@blocknote/core";
import { filterSuggestionItems } from "@blocknote/core/extensions";
import * as locales from "@blocknote/core/locales";
import { BlockNoteView } from "@blocknote/mantine";
import {
  SuggestionMenuController,
  getDefaultReactSlashMenuItems,
  useCreateBlockNote,
  useEditorChange,
} from "@blocknote/react";
import {
  getMultiColumnSlashMenuItems,
  locales as multiColumnLocales,
  multiColumnDropCursor,
  withMultiColumn,
} from "@blocknote/xl-multi-column";
import { useTheme } from "next-themes";
import "@blocknote/core/fonts/inter.css";
import "@blocknote/mantine/style.css";

import type { NoteFile } from "@/shared/types";
import {
  flattenImageColumnLists,
  promoteImageRunsToColumnLists,
} from "@/widgets/note-editor/lib/noteBlockLayout";
import {
  attachmentMarkdown,
  compactAttachmentImageRows,
  resolveAttachmentsToUrls,
  resolveUrlsToAttachments,
} from "@/widgets/note-editor/lib/noteMarkdownBridge";

const EMBED_MIME = "application/x-note-embed";
const noteEditorSchema = withMultiColumn(BlockNoteSchema.create());

type Props = {
  body: string;
  files: NoteFile[];
  onBodyChange: (body: string) => void;
  onAddFile: (file: File) => NoteFile;
  focusRequest?: number;
};

function findFileById(files: NoteFile[], id: string): NoteFile | undefined {
  return files.find((file) => file.id === id || file.name === id);
}

export default function NoteBlockEditor({
  body,
  files,
  onBodyChange,
  onAddFile,
  focusRequest = 0,
}: Props) {
  const { resolvedTheme } = useTheme();
  const lastExportedRef = useRef<string | null>(null);
  const filesRef = useRef(files);
  const onBodyChangeRef = useRef(onBodyChange);
  const onAddFileRef = useRef(onAddFile);
  const handledFocusRef = useRef(0);
  const isSyncingRef = useRef(false);

  filesRef.current = files;
  onBodyChangeRef.current = onBodyChange;
  onAddFileRef.current = onAddFile;

  const editor = useCreateBlockNote({
    schema: noteEditorSchema,
    dropCursor: multiColumnDropCursor,
    dictionary: {
      ...locales.en,
      multi_column: multiColumnLocales.en,
    },
    uploadFile: async (file) => {
      const entry = onAddFileRef.current(file);
      return entry.url ?? `attachment:${entry.id ?? entry.name}`;
    },
  });

  const getSlashMenuItems = useMemo(
    () => async (query: string) =>
      filterSuggestionItems(
        combineByGroup(
          getDefaultReactSlashMenuItems(editor),
          getMultiColumnSlashMenuItems(editor),
        ),
        query,
      ),
    [editor],
  );

  const exportEditorBody = useCallback(() => {
    const flattened = flattenImageColumnLists(editor.document) as typeof editor.document;
    const markdown = compactAttachmentImageRows(
      resolveUrlsToAttachments(editor.blocksToMarkdownLossy(flattened), filesRef.current),
    ).trimEnd();
    lastExportedRef.current = markdown;
    onBodyChangeRef.current(markdown);
    return markdown;
  }, [editor]);

  const syncEditorFromBody = useCallback(
    (markdown: string, noteFiles: NoteFile[]) => {
      const resolved = resolveAttachmentsToUrls(markdown, noteFiles);
      const parsed = editor.tryParseMarkdownToBlocks(resolved || "");
      const blocks = promoteImageRunsToColumnLists(parsed) as typeof editor.document;
      isSyncingRef.current = true;
      editor.replaceBlocks(
        editor.document,
        blocks.length > 0 ? blocks : [{ type: "paragraph" }],
      );
      isSyncingRef.current = false;
      lastExportedRef.current = markdown;
    },
    [editor],
  );

  useLayoutEffect(() => {
    if (body === lastExportedRef.current) return;
    syncEditorFromBody(body, files);
  }, [body, files, syncEditorFromBody]);

  useEditorChange(() => {
    if (isSyncingRef.current) return;
    exportEditorBody();
  }, editor);

  useEffect(() => {
    if (focusRequest <= handledFocusRef.current) return;
    handledFocusRef.current = focusRequest;
    editor.focus();
  }, [editor, focusRequest]);

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (
      event.dataTransfer.types.includes(EMBED_MIME) ||
      event.dataTransfer.types.includes("text/plain")
    ) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      let markdown = event.dataTransfer.getData("text/plain");
      if (!markdown) {
        const embedId = event.dataTransfer.getData(EMBED_MIME);
        const file = embedId ? findFileById(filesRef.current, embedId) : undefined;
        if (file) markdown = attachmentMarkdown(file);
      }
      if (!markdown) return;

      event.preventDefault();
      const resolved = resolveAttachmentsToUrls(markdown, filesRef.current);
      const blocks = promoteImageRunsToColumnLists(
        editor.tryParseMarkdownToBlocks(resolved),
      ) as typeof editor.document;
      if (blocks.length === 0) return;

      const cursor = editor.getTextCursorPosition();
      editor.insertBlocks(blocks, cursor.block, "after");
      exportEditorBody();
    },
    [editor, exportEditorBody],
  );

  const theme = resolvedTheme === "dark" ? "dark" : "light";

  return (
    <div
      className="note-block-editor"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <BlockNoteView editor={editor} theme={theme} slashMenu={false}>
        <SuggestionMenuController triggerCharacter="/" getItems={getSlashMenuItems} />
      </BlockNoteView>
    </div>
  );
}
