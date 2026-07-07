"use client";

import { useEffect, useMemo, type RefObject } from "react";
import { createPortal } from "react-dom";

import type { EmojiCatalogItem } from "@/shared/lib/telegram/emojiCatalog";
import {
  getEmojiCollectionTitle,
} from "@/shared/lib/telegram/emojiCatalog";
import type { TelegramPostEditorHandle } from "@/shared/lib/telegram/tiptap/editorHandle";
import { ComposerEmojiIcon } from "@/shared/ui/icons/composer-emoji-icon";
import { CustomEmojiPreview } from "@/shared/ui/CustomEmojiPreview";
import { getEmojiCollectionNav } from "@/shared/lib/telegram/emojiPickerPaging";
import { resolveEmojiCatalogCollections } from "@/shared/lib/telegram/mergeEmojiCatalog";
import { useEmojiCatalog, useWarmEmojiCatalog } from "@/shared/lib/telegram/useEmojiCatalog";
import { useEmojiPickerMenu } from "@/shared/lib/telegram/useEmojiPickerMenu";
import type { useEmojiPickerMenu as UseEmojiPickerMenu } from "@/shared/lib/telegram/useEmojiPickerMenu";
import { fetchEmojiPreview } from "@/shared/lib/telegram/emojiPreviewClient";

type PickerState = ReturnType<typeof UseEmojiPickerMenu>;

type Props = {
  editorRef: RefObject<TelegramPostEditorHandle | null>;
  picker: PickerState;
  disabled?: boolean;
  onInserted?: () => void;
};

export function EmojiPickerMenu({ editorRef, picker, disabled = false, onInserted }: Props) {
  const catalogEnabled = picker.open && !disabled;
  const { data, isLoading, isError, isFetching } = useEmojiCatalog(catalogEnabled);
  const remoteCollections = data?.collections ?? [];
  const collections = useMemo(
    () => resolveEmojiCatalogCollections(remoteCollections),
    [remoteCollections],
  );
  const loadingRemote = (isLoading || isFetching) && remoteCollections.length === 0;

  const collectionNav = useMemo(
    () => getEmojiCollectionNav(collections, picker.collectionIndex),
    [collections, picker.collectionIndex],
  );

  const collectionItems = collectionNav.collection?.items ?? [];

  useEffect(() => {
    if (!picker.open) return;
    if (picker.collectionIndex >= collections.length && collections.length > 0) {
      picker.setCollectionIndex(0);
    }
  }, [picker.open, collections.length, picker.collectionIndex, picker]);

  const hasMultipleCollections = collections.length > 1;

  useEffect(() => {
    if (!picker.open || collectionNav.collection?.kind !== "custom") return;
    for (const item of collectionItems) {
      if (item.type === "custom") {
        void fetchEmojiPreview(item.documentId);
      }
    }
  }, [picker.open, collectionNav.collection?.kind, collectionItems]);

  function handlePick(item: EmojiCatalogItem) {
    const editor = editorRef.current;
    if (!editor || disabled) return;
    if (item.type === "unicode") {
      editor.insertUnicodeEmoji(item.char);
    } else {
      editor.insertCustomEmoji(item.documentId, item.alt);
    }
    onInserted?.();
    picker.closeMenu();
  }

  const collectionTitle = collectionNav.collection
    ? getEmojiCollectionTitle(collectionNav.collection)
    : "";

  if (!picker.open || typeof document === "undefined") {
    return null;
  }

  const style =
    picker.pos?.mode === "down"
      ? { top: picker.pos.top, left: picker.pos.left }
      : picker.pos?.mode === "up"
        ? { bottom: picker.pos.bottom, left: picker.pos.left }
        : undefined;

  return createPortal(
    <div
      ref={picker.menuRef}
      className="emoji-picker-menu"
      style={{ position: "fixed", ...style }}
      role="dialog"
      aria-label="Выбор эмодзи"
      onMouseDown={(event) => event.preventDefault()}
    >
      {isError ? (
        <div className="emoji-picker-status emoji-picker-status--error">
          Не удалось загрузить наборы Telegram — показаны стандартные смайлы. Попробуйте закрыть и
          открыть пикер снова через несколько секунд.
        </div>
      ) : null}
      {loadingRemote ? (
        <div className="emoji-picker-status emoji-picker-status--hint">
          Подгружаем наборы Telegram… Стандартные уже доступны
        </div>
      ) : null}
      <div className="emoji-picker-body">
      <div className="emoji-picker-header">
        <button
          type="button"
          className="emoji-picker-nav"
          aria-label="Предыдущая коллекция"
          disabled={!collectionNav.canGoPrev}
          onMouseDown={(event) => {
            event.preventDefault();
            if (!collectionNav.canGoPrev) return;
            picker.setCollectionIndex((index) => Math.max(0, index - 1));
          }}
        >
          ‹
        </button>

        <div className="emoji-picker-title" title={collectionTitle}>
          {hasMultipleCollections
            ? `${collectionTitle} (${collectionNav.collectionIndex + 1}/${collections.length})`
            : collectionTitle}
        </div>

        <button
          type="button"
          className="emoji-picker-nav"
          aria-label="Следующая коллекция"
          disabled={!collectionNav.canGoNext}
          onMouseDown={(event) => {
            event.preventDefault();
            if (!collectionNav.canGoNext) return;
            picker.setCollectionIndex((index) => Math.min(collections.length - 1, index + 1));
          }}
        >
          ›
        </button>
      </div>

      <div className="emoji-picker-grid-scroll">
        <div
          className="emoji-picker-grid"
          role="listbox"
          aria-label={collectionTitle}
        >
          {collectionItems.map((item, index) => {
            const key =
              item.type === "unicode"
                ? `u:${item.char}:${index}`
                : `c:${item.documentId}:${index}`;
            return (
              <button
                key={key}
                type="button"
                className="emoji-picker-item"
                role="option"
                title={item.type === "custom" ? item.alt : item.char}
                onMouseDown={(event) => {
                  event.preventDefault();
                  handlePick(item);
                }}
              >
                {item.type === "unicode" ? (
                  <span className="emoji-picker-unicode">{item.char}</span>
                ) : (
                  <CustomEmojiPreview documentId={item.documentId} alt={item.alt} size={26} />
                )}
              </button>
            );
          })}
        </div>
      </div>
      </div>
    </div>,
    document.body,
  );
}

export function EmojiPickerButton({
  editorRef,
  disabled = false,
  className,
  buttonClassName,
  onInserted,
}: {
  editorRef: RefObject<TelegramPostEditorHandle | null>;
  disabled?: boolean;
  className?: string;
  buttonClassName?: string;
  onInserted?: () => void;
}) {
  const picker = useEmojiPickerMenu({ disabled });
  useWarmEmojiCatalog();

  return (
    <div ref={picker.wrapRef} className={["emoji-picker-wrap", className].filter(Boolean).join(" ")}>
      <button
        ref={picker.btnRef}
        type="button"
        className={["emoji-picker-btn", buttonClassName].filter(Boolean).join(" ")}
        aria-label="Эмодзи"
        title="Эмодзи"
        disabled={disabled}
        onClick={picker.onTriggerClick}
      >
        <ComposerEmojiIcon className="emoji-picker-btn-icon" />
      </button>
      <EmojiPickerMenu
        editorRef={editorRef}
        picker={picker}
        disabled={disabled}
        onInserted={onInserted}
      />
    </div>
  );
}
