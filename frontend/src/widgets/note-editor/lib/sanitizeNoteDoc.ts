import type { PartialBlock } from "@blocknote/core";

/** Default BlockNote 0.51 block types (no xl-multi-column). */
const SUPPORTED_BLOCK_TYPES = new Set([
  "audio",
  "bulletListItem",
  "checkListItem",
  "codeBlock",
  "divider",
  "file",
  "heading",
  "image",
  "numberedListItem",
  "paragraph",
  "quote",
  "table",
  "toggleListItem",
  "video",
]);

const BLOCKS_WITH_CHILDREN = new Set([
  "bulletListItem",
  "numberedListItem",
  "checkListItem",
  "toggleListItem",
]);

/** Legacy xl-multi-column containers — flatten children into the document. */
const FLATTEN_CONTAINER_TYPES = new Set(["columnList", "column"]);

/** Internal table nodes that must not appear as top-level blocks. */
const SKIP_AS_BLOCK_TYPES = new Set(["tableRow", "tableCell"]);

function extractInlineText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const item of content) {
    if (!item || typeof item !== "object") continue;
    const inline = item as Record<string, unknown>;
    if (inline.type === "text" && typeof inline.text === "string") {
      parts.push(inline.text);
      continue;
    }
    if (inline.type === "link") {
      parts.push(extractInlineText(inline.content));
    }
  }
  return parts.join("");
}

function textInline(text: string, styles?: Record<string, unknown>) {
  return { type: "text", text, styles: styles ?? {} };
}

function sanitizeInlineContent(content: unknown): unknown[] | undefined {
  if (!Array.isArray(content)) return undefined;

  const out: unknown[] = [];
  for (const item of content) {
    if (!item || typeof item !== "object") continue;
    const inline = item as Record<string, unknown>;
    if (inline.type === "text" && typeof inline.text === "string") {
      const styles =
        inline.styles && typeof inline.styles === "object"
          ? (inline.styles as Record<string, unknown>)
          : {};
      out.push(textInline(inline.text, styles));
      continue;
    }
    if (inline.type === "link" && typeof inline.href === "string") {
      out.push({
        type: "link",
        href: inline.href,
        content: sanitizeInlineContent(inline.content) ?? [],
      });
    }
  }

  return out.length > 0 ? out : undefined;
}

function sanitizeBlockContent(type: string, content: unknown): unknown | undefined {
  if (type === "table" && content && typeof content === "object" && !Array.isArray(content)) {
    return content;
  }
  if (type === "codeBlock" && typeof content === "string") {
    return content;
  }
  return sanitizeInlineContent(content);
}

function flattenInto(
  out: PartialBlock[],
  node: unknown,
  nested: boolean,
  hoisted?: PartialBlock[],
): void {
  if (!node || typeof node !== "object") return;

  const block = node as Record<string, unknown>;
  const type = block.type;
  if (typeof type !== "string") return;

  if (FLATTEN_CONTAINER_TYPES.has(type)) {
    if (Array.isArray(block.children)) {
      for (const child of block.children) flattenInto(out, child, false);
    }
    return;
  }

  if (SKIP_AS_BLOCK_TYPES.has(type)) {
    if (Array.isArray(block.children)) {
      for (const child of block.children) flattenInto(out, child, nested);
    }
    const text = extractInlineText(block.content);
    if (text.trim() && !nested) {
      out.push({ type: "paragraph", content: [textInline(text)] } as PartialBlock);
    }
    return;
  }

  if (nested && !BLOCKS_WITH_CHILDREN.has(type)) {
    const target = hoisted ?? out;
    const text = extractInlineText(block.content);
    if (text.trim()) {
      target.push({ type: "paragraph", content: [textInline(text)] } as PartialBlock);
    }
    if (Array.isArray(block.children)) {
      for (const child of block.children) flattenInto(target, child, false);
    }
    return;
  }

  if (!SUPPORTED_BLOCK_TYPES.has(type)) {
    const text = extractInlineText(block.content);
    if (text.trim()) {
      if (nested && BLOCKS_WITH_CHILDREN.has(type)) {
        return;
      }
      out.push({ type: "paragraph", content: [textInline(text)] } as PartialBlock);
    }
    if (Array.isArray(block.children)) {
      for (const child of block.children) flattenInto(out, child, false);
    }
    return;
  }

  const sanitized: Record<string, unknown> = { type };
  if (typeof block.id === "string") sanitized.id = block.id;
  if (block.props && typeof block.props === "object") sanitized.props = block.props;

  const content = sanitizeBlockContent(type, block.content);
  if (content !== undefined) sanitized.content = content;

  if (BLOCKS_WITH_CHILDREN.has(type) && Array.isArray(block.children)) {
    const children: PartialBlock[] = [];
    const hoistedSiblings: PartialBlock[] = [];
    for (const child of block.children) {
      flattenInto(children, child, true, hoistedSiblings);
    }
    if (children.length > 0) sanitized.children = children;
    out.push(sanitized as PartialBlock);
    for (const sibling of hoistedSiblings) out.push(sibling);
    return;
  }

  out.push(sanitized as PartialBlock);
}

/** Drop or flatten blocks that the default BlockNote schema cannot load. */
export function sanitizeNoteDoc(doc: unknown[]): PartialBlock[] {
  const out: PartialBlock[] = [];
  for (const node of doc) flattenInto(out, node, false);
  return out;
}
