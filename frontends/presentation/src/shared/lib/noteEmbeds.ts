export type {
  BodyLine,
  CellPos,
  ImageGridSlotItem,
  LineCell,
  NoteBodySegment,
  NotePreviewItem,
  NotePreviewLine,
} from "@/shared/lib/noteEmbeds/types";

export {
  EMBED_IMAGE_SLOT_GAP,
  EMBED_IMAGE_SLOT_H,
  EMBED_IMAGE_SLOT_W,
  MAX_IMAGES_PER_EMBED_ROW,
} from "@/shared/lib/noteEmbeds/types";

export { embedToken, parseNoteBody, serializeNoteBody } from "@/shared/lib/noteEmbeds/bodyParse";

export { findNoteFile, isImageEmbed } from "@/shared/lib/noteEmbeds/embedFiles";

export {
  canonicalNoteBody,
  countEmbedRowImages,
  isEmbedLine,
  isImageEmbedRow,
  isTextLine,
  linesToBody,
  normalizeEmbedImageRows,
  normalizeNoteBody,
  segmentsToLines,
} from "@/shared/lib/noteEmbeds/lines";

export {
  buildImageGridSlotLayout,
  dropBeforeToImageSlot,
  imageGridSlotToDropBefore,
  visibleEmbedIndices,
} from "@/shared/lib/noteEmbeds/imageGrid";

export {
  insertEmbedAt,
  insertEmbedInBody,
  isDropNoop,
  moveEmbedAt,
  moveEmbedToImageGridSlot,
  moveEmbedToLineBefore,
} from "@/shared/lib/noteEmbeds/embedMoves";

export { buildNotePreviewLines } from "@/shared/lib/noteEmbeds/preview";

export { splitLineHighlightParts } from "@/shared/lib/noteEmbeds/lineHighlight";

export {
  bodyToEditLines,
  lineEditContent,
  parseEmbedNameFromEditable,
  splitLineAtCaret,
  updateEmbedCell,
  updateTextCell,
} from "@/shared/lib/noteEmbeds/textEdit";
