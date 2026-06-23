"use client";

/**
 * Renders a note body (CommonMark + GFM) as rich HTML.
 *
 * Handles:
 * - Tables (GFM)
 * - Images: ![alt](attachment:<id>) → resolved from files[] by id, shown inline or as chip
 * - Files: [name](attachment:<id>) → chip with link
 * - Image grid: consecutive image-only paragraphs grouped in rows of ≤ MAX_IMAGES_PER_ROW
 */

import { type ReactNode, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { NoteFile } from "@/shared/types";

const ATTACHMENT_PREFIX = "attachment:";
const MAX_IMAGES_PER_ROW = 3;

function resolveFile(files: NoteFile[], src: string): NoteFile | undefined {
  if (!src.startsWith(ATTACHMENT_PREFIX)) return undefined;
  const id = src.slice(ATTACHMENT_PREFIX.length);
  return files.find((f) => f.id === id);
}

function isImageFile(file: NoteFile | undefined): boolean {
  return !!file && (file.type?.startsWith("image/") ?? false);
}

type AttachmentImageProps = {
  file: NoteFile;
  alt: string;
};

function AttachmentImage({ file, alt }: AttachmentImageProps) {
  if (file.url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="note-inline-image" src={file.url} alt={alt || file.name} draggable={false} />;
  }
  return (
    <span className="note-embed-chip">
      <span className="note-embed-token">[{file.name}]</span>
    </span>
  );
}

type AttachmentChipProps = {
  file: NoteFile;
  label: string;
};

function AttachmentChip({ file, label }: AttachmentChipProps) {
  return (
    <span className="note-embed-chip note-embed-token">
      <a
        href={file.url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => !file.url && e.preventDefault()}
      >
        {label || file.name}
      </a>
    </span>
  );
}

/**
 * Groups consecutive image nodes (from adjacent markdown image lines)
 * into rows of MAX_IMAGES_PER_ROW.
 */
function groupImageRows(nodes: ReactNode[]): ReactNode[] {
  const result: ReactNode[] = [];
  let imageGroup: ReactNode[] = [];

  const flushGroup = () => {
    if (imageGroup.length === 0) return;
    // Split into rows of MAX_IMAGES_PER_ROW
    for (let i = 0; i < imageGroup.length; i += MAX_IMAGES_PER_ROW) {
      const row = imageGroup.slice(i, i + MAX_IMAGES_PER_ROW);
      result.push(
        <div key={`img-row-${result.length}`} className="note-image-grid-row">
          {row}
        </div>,
      );
    }
    imageGroup = [];
  };

  for (const node of nodes) {
    if (
      node !== null &&
      typeof node === "object" &&
      "type" in node &&
      (node as React.ReactElement).type === AttachmentImage
    ) {
      imageGroup.push(node);
    } else {
      flushGroup();
      result.push(node);
    }
  }
  flushGroup();
  return result;
}

type Props = {
  body: string;
  files: NoteFile[];
  className?: string;
};

export default function NoteMarkdownRenderer({ body, files, className }: Props) {
  const components = useMemo(
    () => ({
      // Images: resolve attachment:id → inline img or chip
      img({ src, alt }: { src?: string; alt?: string }) {
        const file = resolveFile(files, src ?? "");
        if (!file) {
          if (src?.startsWith(ATTACHMENT_PREFIX)) {
            return <span className="note-embed-chip note-embed-token">[{alt || src}]</span>;
          }
          // eslint-disable-next-line @next/next/no-img-element
          return <img src={src} alt={alt} />;
        }
        if (isImageFile(file)) {
          return <AttachmentImage file={file} alt={alt ?? ""} />;
        }
        return <AttachmentChip file={file} label={alt ?? ""} />;
      },

      // Links: resolve attachment:id → chip, else normal link
      a({ href, children }: { href?: string; children?: ReactNode }) {
        const file = resolveFile(files, href ?? "");
        if (file) {
          const label = typeof children === "string" ? children : file.name;
          return <AttachmentChip file={file} label={label} />;
        }
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      },

      // Paragraph: if it contains only images, unwrap them for grid grouping
      p({ children }: { children?: ReactNode }) {
        const childArray = Array.isArray(children) ? children : [children];
        const allImages = childArray.every(
          (child) =>
            child === null ||
            child === undefined ||
            (typeof child === "object" &&
              "type" in (child as React.ReactElement) &&
              (child as React.ReactElement).type === AttachmentImage),
        );
        if (allImages) {
          const images = childArray.filter(Boolean);
          return <>{groupImageRows(images)}</>;
        }
        return <p>{children}</p>;
      },

      // Tables: wrap in scrollable container for overflow
      table({ children }: { children?: ReactNode }) {
        return (
          <div className="note-table-wrapper">
            <table className="note-table">{children}</table>
          </div>
        );
      },
    }),
    [files],
  );

  if (!body) {
    return <span className={`note-body-empty${className ? ` ${className}` : ""}`}>Заметка пустая</span>;
  }

  return (
    <div className={`note-body-document note-body-document--markdown${className ? ` ${className}` : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components as never}>
        {body}
      </ReactMarkdown>
    </div>
  );
}
