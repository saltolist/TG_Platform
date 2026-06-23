import type { PartialBlock } from "@blocknote/core";

/** Max images per row in canonical note format (matches NoteMarkdownRenderer). */
export const MAX_IMAGES_PER_ROW = 3;

type AnyBlock = PartialBlock<any, any, any>;

function isImageBlock(block: AnyBlock): boolean {
  return block.type === "image";
}

function isEmptyParagraph(block: AnyBlock): boolean {
  if (block.type !== "paragraph") return false;
  const content = block.content;
  if (!content || !Array.isArray(content) || content.length === 0) return true;
  return content.every(
    (item) =>
      typeof item === "object" &&
      item !== null &&
      "type" in item &&
      item.type === "text" &&
      (!("text" in item) || String(item.text).trim() === ""),
  );
}

function makeColumnList(imageBlocks: AnyBlock[]): AnyBlock {
  return {
    type: "columnList",
    children: imageBlocks.map((image) => ({
      type: "column",
      props: { width: 1 },
      children: [image],
    })),
  };
}

/** Split a run of image blocks into columnList groups (max 3 per row). */
function imageRunToBlocks(images: AnyBlock[]): AnyBlock[] {
  if (images.length === 0) return [];
  if (images.length === 1) return [images[0]!];

  const result: AnyBlock[] = [];
  for (let i = 0; i < images.length; i += MAX_IMAGES_PER_ROW) {
    const chunk = images.slice(i, i + MAX_IMAGES_PER_ROW);
    if (chunk.length === 1) {
      result.push(chunk[0]!);
    } else {
      result.push(makeColumnList(chunk));
    }
  }
  return result;
}

/**
 * Promote consecutive image blocks (separated only by empty paragraphs) into
 * columnList layouts for side-by-side editing.
 *
 * Full round-trip is only guaranteed for image-only rows (2–3 images).
 */
export function promoteImageRunsToColumnLists(blocks: AnyBlock[]): AnyBlock[] {
  const result: AnyBlock[] = [];
  let imageRun: AnyBlock[] = [];

  const flushRun = () => {
    if (imageRun.length === 0) return;
    result.push(...imageRunToBlocks(imageRun));
    imageRun = [];
  };

  for (const block of blocks) {
    if (isImageBlock(block)) {
      imageRun.push(block);
      continue;
    }
    if (imageRun.length > 0 && isEmptyParagraph(block)) {
      continue;
    }
    flushRun();
    result.push(block);
  }

  flushRun();
  return result;
}

function columnHasSingleImage(column: AnyBlock): AnyBlock | null {
  if (column.type !== "column") return null;
  const children = column.children;
  if (!children || children.length !== 1) return null;
  const child = children[0]!;
  return isImageBlock(child) ? child : null;
}

function isImageOnlyColumnList(block: AnyBlock): AnyBlock[] | null {
  if (block.type !== "columnList") return null;
  const columns = block.children;
  if (!columns || columns.length < 2) return null;

  const images: AnyBlock[] = [];
  for (const column of columns) {
    const image = columnHasSingleImage(column);
    if (!image) return null;
    images.push(image);
  }
  return images;
}

/**
 * Flatten image-only columnList blocks back to consecutive image blocks before
 * markdown export. Mixed/text column layouts are left unchanged (lossy export).
 */
export function flattenImageColumnLists(blocks: AnyBlock[]): AnyBlock[] {
  const result: AnyBlock[] = [];

  for (const block of blocks) {
    const images = isImageOnlyColumnList(block);
    if (images) {
      result.push(...images);
    } else {
      result.push(block);
    }
  }

  return result;
}
