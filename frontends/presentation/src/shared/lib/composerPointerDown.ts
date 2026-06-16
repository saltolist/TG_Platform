import type { MouseEvent } from "react";

const COMPOSER_BOX_SELECTOR = ".input-box";
const COMPOSER_FIELD_SELECTOR = ".composer-editor, textarea";
const COMPOSER_CONTROL_SELECTOR =
  "button, .model-picker, .attach-wrap, .inline-chip-remove, .comment-composer-reply-cancel, .tg-media, .tg-media-remove";

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
