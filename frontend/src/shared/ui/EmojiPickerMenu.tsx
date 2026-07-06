"use client";

import { useEffect, useMemo, type RefObject } from "react";
import { createPortal } from "react-dom";

import type { EmojiCatalogItem } from "@/shared/lib/telegram/emojiCatalog";
import { FALLBACK_EMOJI_CATALOG } from "@/shared/lib/telegram/emojiCatalog";
import { CustomEmojiPreview } from "@/shared/ui/CustomEmojiPreview";
import {
  getEmojiCollectionNav,
  getEmojiItemsPage,
} from "@/shared/lib/telegram/emojiPickerPaging";
import { useEmojiCatalog, useWarmEmojiCatalog } from "@/shared/lib/telegram/useEmojiCatalog";
import { useEmojiPickerMenu } from "@/shared/lib/telegram/useEmojiPickerMenu";
import type { useEmojiPickerMenu as UseEmojiPickerMenu } from "@/shared/lib/telegram/useEmojiPickerMenu";
import {
  autoResizeRichTextEditor,
  insertCustomEmoji,
  insertUnicodeEmoji,
} from "@/shared/lib/telegram/richTextEditorDom";
import { hydrateCustomEmojiInDom } from "@/shared/lib/telegram/hydrateCustomEmojiDom";
import { fetchEmojiPreview } from "@/shared/lib/telegram/emojiPreviewClient";

type PickerState = ReturnType<typeof UseEmojiPickerMenu>;

type Props = {
  editorRef: RefObject<HTMLDivElement | null>;
  picker: PickerState;
  disabled?: boolean;
  onInserted?: () => void;
};

export function EmojiPickerMenu({ editorRef, picker, disabled = false, onInserted }: Props) {
  const catalogEnabled = picker.open && !disabled;
  const { data, isLoading, isError, isFetching } = useEmojiCatalog(catalogEnabled);
  const remoteCollections = data?.collections ?? [];
  const collections =
    remoteCollections.length > 0 ? remoteCollections : FALLBACK_EMOJI_CATALOG.collections;
  const loadingRemote = (isLoading || isFetching) && remoteCollections.length === 0;

  const collectionNav = useMemo(
    () => getEmojiCollectionNav(collections, picker.collectionIndex),
    [collections, picker.collectionIndex],
  );

  const itemsPage = useMemo(
    () => getEmojiItemsPage(collectionNav.collection?.items ?? [], picker.itemPage),
    [collectionNav.collection?.items, picker.itemPage],
  );

  useEffect(() => {
    if (!picker.open) return;
    if (picker.collectionIndex >= collections.length && collections.length > 0) {
      picker.setCollectionIndex(0);
      picker.setItemPage(0);
    }
  }, [picker.open, collections.length, picker.collectionIndex, picker]);

  const hasMultipleCollections = collections.length > 1;

  useEffect(() => {
    if (!picker.open || collectionNav.collection?.kind !== "custom") return;
    for (const item of itemsPage.items) {
      if (item.type === "custom") {
        void fetchEmojiPreview(item.documentId);
      }
    }
  }, [picker.open, collectionNav.collection?.kind, itemsPage.items]);

  function handlePick(item: EmojiCatalogItem) {
    const root = editorRef.current;
    if (!root || disabled) return;
    if (item.type === "unicode") {
      insertUnicodeEmoji(root, item.char);
    } else {
      insertCustomEmoji(root, item.documentId, item.alt);
    }
    autoResizeRichTextEditor(root);
    onInserted?.();
    picker.closeMenu();
    hydrateCustomEmojiInDom(root);
  }

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
          Подгружаем наборы Telegram… Смайлы уже доступны
        </div>
      ) : null}
      <div className="emoji-picker-header">
            {collectionNav.canGoPrev ? (
              <button
                type="button"
                className="emoji-picker-nav"
                aria-label="Предыдущая коллекция"
                onMouseDown={(event) => {
                  event.preventDefault();
                  picker.setCollectionIndex((index) => Math.max(0, index - 1));
                  picker.resetItemPage();
                }}
              >
                ‹
              </button>
            ) : (
              <span className="emoji-picker-nav emoji-picker-nav--placeholder" aria-hidden="true" />
            )}

            <div className="emoji-picker-title" title={collectionNav.collection?.title}>
              {hasMultipleCollections
                ? `${collectionNav.collection?.title ?? ""} (${collectionNav.collectionIndex + 1}/${collections.length})`
                : (collectionNav.collection?.title ?? "")}
            </div>

            {collectionNav.canGoNext ? (
              <button
                type="button"
                className="emoji-picker-nav"
                aria-label="Следующая коллекция"
                onMouseDown={(event) => {
                  event.preventDefault();
                  picker.setCollectionIndex((index) =>
                    Math.min(collections.length - 1, index + 1),
                  );
                  picker.resetItemPage();
                }}
              >
                ›
              </button>
            ) : (
              <span className="emoji-picker-nav emoji-picker-nav--placeholder" aria-hidden="true" />
            )}
      </div>

      {itemsPage.totalPages > 1 ? (
        <div className="emoji-picker-subnav">
              {itemsPage.canGoPrev ? (
                <button
                  type="button"
                  className="emoji-picker-subnav-btn"
                  aria-label="Предыдущая страница"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    picker.setItemPage((page) => Math.max(0, page - 1));
                  }}
                >
                  ‹
                </button>
              ) : null}
              <span className="emoji-picker-subnav-label">
                {itemsPage.page + 1} / {itemsPage.totalPages}
              </span>
              {itemsPage.canGoNext ? (
                <button
                  type="button"
                  className="emoji-picker-subnav-btn"
                  aria-label="Следующая страница"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    picker.setItemPage((page) => Math.min(itemsPage.totalPages - 1, page + 1));
                  }}
                >
                  ›
                </button>
              ) : null}
        </div>
      ) : null}

      <div
        className="emoji-picker-grid"
        role="listbox"
        aria-label={collectionNav.collection?.title}
      >
            {itemsPage.items.map((item, index) => {
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
                    <CustomEmojiPreview
                      documentId={item.documentId}
                      alt={item.alt}
                      size={26}
                    />
                  )}
                </button>
              );
            })}
      </div>
    </div>,
    document.body,
  );
}

export function EmojiPickerButton({
  editorRef,
  disabled = false,
  className,
  onInserted,
}: {
  editorRef: RefObject<HTMLDivElement | null>;
  disabled?: boolean;
  className?: string;
  onInserted?: () => void;
}) {
  const picker = useEmojiPickerMenu({ disabled });
  useWarmEmojiCatalog();

  return (
    <div ref={picker.wrapRef} className={["emoji-picker-wrap", className].filter(Boolean).join(" ")}>
      <button
        ref={picker.btnRef}
        type="button"
        className="emoji-picker-btn"
        aria-label="Эмодзи"
        title="Эмодзи"
        disabled={disabled}
        onClick={picker.onTriggerClick}
      >
        ☺
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
