import type { MouseEvent } from "react";

const COMPOSER_BOX_SELECTOR = ".input-box";
const COMPOSER_FIELD_SELECTOR = ".composer-editor, textarea, .rich-text-input";
const COMPOSER_CONTROL_SELECTOR =
  "button, .model-picker, .attach-wrap, .emoji-picker-wrap, .inline-chip-remove, .comment-composer-reply-cancel, .post-comment-actions, .tg-media, .tg-media-remove, .rich-text-format-bubble, .rich-text-format-bubble-btn, .rich-text-format-bubble-nav, .emoji-picker-menu, .emoji-picker-btn, .emoji-picker-item, .emoji-picker-nav, .emoji-picker-grid-scroll";

function blurActiveComposerField() {
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.closest(COMPOSER_FIELD_SELECTOR)) {
    active.blur();
  }
}

function focusComposerField(box: Element) {
  const field = box.querySelector<HTMLElement>(COMPOSER_FIELD_SELECTOR);
  field?.focus();
}

/**
 * Клик по карточке (.input-box) — фокус в поле; клик снаружи карточки — без фокуса.
 * Кнопки и медиа внутри карточки обрабатываются как обычно.
 */
export function onComposerShellMouseDown(e: MouseEvent<HTMLElement>) {
  const el = e.target as HTMLElement;
  const box = el.closest(COMPOSER_BOX_SELECTOR);

  if (!box) {
    e.preventDefault();
    blurActiveComposerField();
    return;
  }

  if (el.closest(COMPOSER_CONTROL_SELECTOR)) return;
  if (el.closest(COMPOSER_FIELD_SELECTOR)) return;

  e.preventDefault();
  focusComposerField(box);
}
