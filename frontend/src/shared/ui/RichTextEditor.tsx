"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type RefObject,
} from "react";

import {
  applyRichTextFormat,
  autoResizeRichTextEditor,
  serializeRichTextEditor,
  setRichTextContent,
  type PostTextContent,
  type RichTextFormat,
} from "@/shared/lib/telegram/richTextEditorDom";
import { useRichTextFormatBubble } from "@/shared/lib/telegram/useRichTextFormatBubble";
import { hydrateCustomEmojiInDom } from "@/shared/lib/telegram/hydrateCustomEmojiDom";
import { RichTextFormatBubble } from "@/shared/ui/RichTextFormatBubble";

type Props = {
  value: PostTextContent;
  onChange: (value: PostTextContent) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  placeholder?: string;
  className?: string;
  editorRef?: RefObject<HTMLDivElement | null>;
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
  const localRef = useRef<HTMLDivElement>(null);
  const ref = editorRef ?? localRef;
  const lastSerializedRef = useRef("");
  const isEmpty = !value.text.trim() && !value.textHtml?.trim();
  const { bubble, refreshBubble, closeBubble } = useRichTextFormatBubble(ref, disabled);

  const syncFromDom = useCallback(() => {
    const root = ref.current;
    if (!root) return;
    const next = serializeRichTextEditor(root);
    const serialized = JSON.stringify(next);
    if (serialized === lastSerializedRef.current) return;
    lastSerializedRef.current = serialized;
    onChange(next);
  }, [onChange, ref]);

  const hydrateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleHydrate = useCallback(() => {
    const root = ref.current;
    if (!root) return;
    if (hydrateTimerRef.current) clearTimeout(hydrateTimerRef.current);
    hydrateTimerRef.current = setTimeout(() => {
      hydrateCustomEmojiInDom(root);
    }, 120);
  }, [ref]);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const serialized = JSON.stringify(value);
    if (serialized === lastSerializedRef.current) return;
    setRichTextContent(root, value);
    lastSerializedRef.current = serialized;
    autoResizeRichTextEditor(root, minHeight);
    closeBubble();
    scheduleHydrate();
  }, [closeBubble, minHeight, ref, scheduleHydrate, value]);

  useEffect(
    () => () => {
      if (hydrateTimerRef.current) clearTimeout(hydrateTimerRef.current);
    },
    [],
  );

  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    autoResizeRichTextEditor(root, minHeight);
  }, [minHeight, ref, value.text, value.textHtml]);

  const handleFormat = useCallback(
    (format: RichTextFormat) => {
      if (disabled) return;
      const root = ref.current;
      if (!root) return;
      root.focus();
      applyRichTextFormat(format);
      syncFromDom();
      autoResizeRichTextEditor(root, minHeight);
      refreshBubble();
    },
    [disabled, minHeight, ref, refreshBubble, syncFromDom],
  );

  return (
    <div className="rich-text-editor">
      <div
        ref={ref}
        id={id}
        className={[
          "rich-text-input",
          "tg-formatted-text",
          isEmpty ? "rich-text-input--empty" : "",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        contentEditable={!disabled}
        role="textbox"
        aria-multiline="true"
        aria-label={ariaLabel}
        aria-disabled={disabled}
        data-placeholder={placeholder}
        suppressContentEditableWarning
        onInput={() => {
          syncFromDom();
          const root = ref.current;
          if (root) {
            scheduleHydrate();
            autoResizeRichTextEditor(root, minHeight);
          }
        }}
        onMouseUp={refreshBubble}
        onKeyUp={refreshBubble}
        onKeyDown={onKeyDown}
        onBlur={syncFromDom}
      />
      <RichTextFormatBubble bubble={bubble} onFormat={handleFormat} />
    </div>
  );
}
