"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  type KeyboardEvent,
  type RefObject,
} from "react";

import type { RichTextFormat } from "@/shared/lib/telegram/richTextFormat";
import { applyTelegramFormat } from "@/shared/lib/telegram/tiptap/applyTelegramFormat";
import { createEditorHandle, type TelegramPostEditorHandle } from "@/shared/lib/telegram/tiptap/editorHandle";
import type { PostTextContent } from "@/shared/lib/telegram/tiptap/postTextContent";
import { getTelegramPostEditorExtensions } from "@/shared/lib/telegram/tiptap/telegramEditorExtensions";
import {
  editorToPostContent,
  postContentToEditorHtml,
} from "@/shared/lib/telegram/tiptap/telegramHtmlBridge";
import { useRichTextFormatBubble } from "@/shared/lib/telegram/useRichTextFormatBubble";
import { RichTextFormatBubble } from "@/shared/ui/RichTextFormatBubble";

type Props = {
  value: PostTextContent;
  onChange: (value: PostTextContent) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  placeholder?: string;
  className?: string;
  editorRef?: RefObject<TelegramPostEditorHandle | null>;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
  minHeight?: number;
};

export function RichTextEditor({
  value,
  onChange,
  onKeyDown,
  placeholder,
  className,
  editorRef,
  disabled = false,
  id,
  ariaLabel,
  minHeight = 16,
}: Props) {
  const lastSerializedRef = useRef("");
  const wrapperRef = useRef<HTMLDivElement>(null);
  const isEmpty = !value.text.trim() && !value.textHtml?.trim();

  const extensions = useMemo(
    () => getTelegramPostEditorExtensions(placeholder),
    [placeholder],
  );

  const editor = useEditor({
    extensions,
    content: postContentToEditorHtml(value),
    editable: !disabled,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        ...(id ? { id } : {}),
        class: [
          "rich-text-input",
          "tg-formatted-text",
          "ProseMirror",
          isEmpty ? "rich-text-input--empty" : "",
          className,
        ]
          .filter(Boolean)
          .join(" "),
        role: "textbox",
        "aria-multiline": "true",
        "aria-label": ariaLabel ?? "",
        "aria-disabled": String(disabled),
      },
    },
    onUpdate: ({ editor: currentEditor }) => {
      const next = editorToPostContent(currentEditor);
      const serialized = JSON.stringify(next);
      if (serialized === lastSerializedRef.current) return;
      lastSerializedRef.current = serialized;
      onChange(next);
      autoResizeEditor(wrapperRef.current, minHeight);
    },
  });

  const { bubble, openBubble, closeBubble } = useRichTextFormatBubble(editor, disabled);

  useEffect(() => {
    if (!editorRef) return;
    editorRef.current = createEditorHandle(editor);
    return () => {
      editorRef.current = null;
    };
  }, [editor, editorRef]);

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!disabled);
  }, [disabled, editor]);

  useEffect(() => {
    if (!editor) return;
    const serialized = JSON.stringify(value);
    if (serialized === lastSerializedRef.current) return;
    editor.commands.setContent(postContentToEditorHtml(value), { emitUpdate: false });
    lastSerializedRef.current = serialized;
    autoResizeEditor(wrapperRef.current, minHeight);
    closeBubble();
  }, [closeBubble, editor, minHeight, value]);

  useLayoutEffect(() => {
    autoResizeEditor(wrapperRef.current, minHeight);
  }, [minHeight, value.text, value.textHtml]);

  const handleFormat = useCallback(
    (format: RichTextFormat) => {
      if (disabled || !editor) return;
      applyTelegramFormat(editor, format);
      openBubble();
      autoResizeEditor(wrapperRef.current, minHeight);
    },
    [disabled, editor, minHeight, openBubble],
  );

  if (!editor) {
    return <div className="rich-text-editor" ref={wrapperRef} />;
  }

  return (
    <div className="rich-text-editor" ref={wrapperRef}>
      <EditorContent
        editor={editor}
        onKeyDown={(event) => {
          onKeyDown?.(event);
        }}
        onBlur={() => {
          if (!editor) return;
          const next = editorToPostContent(editor);
          const serialized = JSON.stringify(next);
          if (serialized !== lastSerializedRef.current) {
            lastSerializedRef.current = serialized;
            onChange(next);
          }
        }}
      />
      <RichTextFormatBubble bubble={bubble} onFormat={handleFormat} />
    </div>
  );
}

function autoResizeEditor(root: HTMLElement | null, minHeight = 16): void {
  const prose = root?.querySelector<HTMLElement>(".ProseMirror");
  if (!prose) return;
  prose.style.height = "auto";
  prose.style.height = `${Math.max(minHeight, prose.scrollHeight)}px`;
}
