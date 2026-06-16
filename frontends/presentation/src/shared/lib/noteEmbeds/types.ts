export type NoteBodySegment =
  | { type: "text"; content: string }
  | { type: "embed"; name: string };

export type LineCell = { type: "text"; content: string } | { type: "embed"; name: string };
export type BodyLine = { cells: LineCell[] };
export type CellPos = { line: number; cell: number };

export type ImageGridSlotItem = {
  cell: LineCell;
  pos: CellPos;
  isPlaceholder: boolean;
};

export type NotePreviewItem =
  | { kind: "gap"; key: string }
  | { kind: "cell"; cell: LineCell; pos: CellPos; isPlaceholder?: boolean };

export type NotePreviewLine = {
  lineKey: string;
  isEmbed: boolean;
  isImageGrid: boolean;
  lineIndex: number;
  items: NotePreviewItem[];
};

export const MAX_IMAGES_PER_EMBED_ROW = 3;
/** Должно совпадать с `--note-embed-image-max-w` в tokens.css (превью при перетаскивании). */
export const EMBED_IMAGE_SLOT_W = 400;
export const EMBED_IMAGE_SLOT_H = 200;
export const EMBED_IMAGE_SLOT_GAP = 8;

export const EMBED_RE = /\[([^\]]+)\]/g;
