import { EMBED_IMAGE_SLOT_H, EMBED_IMAGE_SLOT_W } from "@/shared/lib/noteEmbeds";

export const EMBED_MIME = "application/x-note-embed";

/** Граница «перед строкой / после строки» (доля высоты строки сверху). */
export const TEXT_DROP_BOUNDARY_FRAC = 0.5;

export const FLEX_DROP_X_HYST_PX = 48;
export const IMAGE_GRID_BOTTOM_SIDE_DROP_TOLERANCE_PX = 24;

/** Плавающая карточка и слот вставки при перетаскивании вложения. */
export const DRAG_CARD_W = EMBED_IMAGE_SLOT_W;
export const DRAG_CARD_H = EMBED_IMAGE_SLOT_H;

/** В режиме просмотра не начинаем drag сразу — иначе ломаются клики по ссылкам на файлы. */
export const VIEW_EMBED_DRAG_THRESHOLD_SQ = 36;
