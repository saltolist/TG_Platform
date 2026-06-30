"use client";

import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  citationChipLabel,
  isNoteCitationHref,
  prepareNoteCitationsForDisplay,
  resolveNoteCitationHref,
  splitNoteCitationSegments,
  type NoteCitationSegment,
} from "@/shared/lib/noteCitation";
import ChatCitationChip from "@/shared/ui/ChatCitationChip";

type Props = {
  text: string;
  className?: string;
  validNotePaths?: ReadonlySet<string>;
};

function allowNoteUrls(url: string): string {
  if (isNoteCitationHref(url)) return url;
  return defaultUrlTransform(url);
}

function renderCitationSegment(seg: Extract<NoteCitationSegment, { type: "cite" }>, key: string) {
  const noteHref = resolveNoteCitationHref(seg.href);
  if (!noteHref) return null;

  const fullTitle = seg.title.trim() || undefined;
  const label = citationChipLabel(seg.title);

  return (
    <span key={key} className="chat-citation-inline">
      <ChatCitationChip href={noteHref} label={label} title={fullTitle} />
    </span>
  );
}

function MarkdownInline({ text }: { text: string }) {
  if (!text.trim()) return null;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={allowNoteUrls}
      components={{
        p: ({ children }) => <span className="chat-markdown-inline">{children}</span>,
        a: ({ href, children }) => {
          if (href && isNoteCitationHref(href)) {
            return renderCitationSegment({ type: "cite", title: String(children), href }, href);
          }
          if (href?.startsWith("/") || href?.startsWith("http://") || href?.startsWith("https://")) {
            const external = href.startsWith("http");
            return (
              <a
                href={href}
                className="chat-markdown-link"
                {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
              >
                {children}
              </a>
            );
          }
          return <span>{children}</span>;
        },
        strong: ({ children }) => <strong className="chat-markdown-strong">{children}</strong>,
        em: ({ children }) => <em className="chat-markdown-em">{children}</em>,
        code: ({ children }) => <code className="chat-markdown-code">{children}</code>,
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function MarkdownBlock({ text }: { text: string }) {
  if (!text.trim()) return null;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={allowNoteUrls}
      components={{
        a: ({ href, children }) => {
          if (href && isNoteCitationHref(href)) {
            return renderCitationSegment({ type: "cite", title: String(children), href }, href);
          }
          if (href?.startsWith("/") || href?.startsWith("http://") || href?.startsWith("https://")) {
            const external = href.startsWith("http");
            return (
              <a
                href={href}
                className="chat-markdown-link"
                {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
              >
                {children}
              </a>
            );
          }
          return <span>{children}</span>;
        },
        p: ({ children }) => <p className="chat-markdown-p">{children}</p>,
        ul: ({ children }) => <ul className="chat-markdown-ul">{children}</ul>,
        ol: ({ children }) => <ol className="chat-markdown-ol">{children}</ol>,
        li: ({ children }) => <li className="chat-markdown-li">{children}</li>,
        strong: ({ children }) => <strong className="chat-markdown-strong">{children}</strong>,
        em: ({ children }) => <em className="chat-markdown-em">{children}</em>,
        code: ({ children, className: codeClass }) =>
          codeClass ? (
            <code className={`chat-markdown-code-block ${codeClass}`}>{children}</code>
          ) : (
            <code className="chat-markdown-code">{children}</code>
          ),
        pre: ({ children }) => <pre className="chat-markdown-pre">{children}</pre>,
        blockquote: ({ children }) => (
          <blockquote className="chat-markdown-blockquote">{children}</blockquote>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function renderParagraphSegments(paragraph: string, keyPrefix: string): ReactNode {
  const segments = splitNoteCitationSegments(paragraph);
  const firstCiteIdx = segments.findIndex((seg) => seg.type === "cite");

  if (firstCiteIdx < 0) {
    return <MarkdownBlock key={keyPrefix} text={paragraph} />;
  }

  const bodySegments = segments.slice(0, firstCiteIdx);
  const citeSegments = segments
    .slice(firstCiteIdx)
    .filter((seg): seg is Extract<NoteCitationSegment, { type: "cite" }> => seg.type === "cite");

  return (
    <p key={keyPrefix} className="chat-markdown-p">
      {bodySegments.map((seg, index) => {
        if (seg.type !== "text") return null;
        return <MarkdownInline key={`${keyPrefix}-text-${index}`} text={seg.text} />;
      })}
      {citeSegments.length > 0 ? (
        <>
          {bodySegments.some((seg) => seg.type === "text" && seg.text.trim()) ? " " : null}
          <span className="chat-citation-group">
            {citeSegments.map((seg, index) =>
              renderCitationSegment(seg, `${keyPrefix}-cite-${index}`),
            )}
          </span>
        </>
      ) : null}
    </p>
  );
}

export default function ChatMarkdown({ text, className, validNotePaths }: Props) {
  const prepared = prepareNoteCitationsForDisplay(text, validNotePaths);
  if (!prepared.trim()) return null;

  const blocks = prepared.split(/\n{2,}/);

  return (
    <div className={`chat-markdown${className ? ` ${className}` : ""}`}>
      {blocks.map((block, index) => renderParagraphSegments(block, `block-${index}`))}
    </div>
  );
}
