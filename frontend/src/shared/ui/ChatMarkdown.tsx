"use client";

import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  isNoteCitationHref,
  prepareNoteCitationsForDisplay,
  resolveNoteCitationHref,
  resolveNoteCitationChipLabel,
  splitNoteCitationSegments,
  type NoteCitationSegment,
} from "@/shared/lib/noteCitation";
import { prepareWebCitationsForDisplay, resolveWebCitationHref, WEB_CITE_HREF_PREFIX } from "@/shared/lib/webCitation";
import ChatCitationChip from "@/shared/ui/ChatCitationChip";
import ChatWebCitationChip from "@/shared/ui/ChatWebCitationChip";
import type { WebCite } from "@/shared/api/schemas/post";

type Props = {
  text: string;
  className?: string;
  validNotePaths?: ReadonlySet<string>;
  noteTitleByPath?: ReadonlyMap<string, string>;
  webCites?: WebCite[];
};

function allowNoteUrls(url: string): string {
  if (isNoteCitationHref(url)) return url;
  if (url.startsWith(WEB_CITE_HREF_PREFIX)) return url;
  return defaultUrlTransform(url);
}

function renderWebCitationChip(cite: WebCite, key: string) {
  return (
    <span key={key} className="chat-citation-inline">
      <ChatWebCitationChip url={cite.url} title={cite.title} domain={cite.domain} />
    </span>
  );
}

function renderWebCitationLink(href: string, webCites: WebCite[] | undefined, key: string) {
  const index = resolveWebCitationHref(href);
  if (!index) return null;
  const cite = webCites?.[index - 1];
  if (!cite) return <span key={key}>[{index}]</span>;
  return renderWebCitationChip(cite, key);
}

function renderCitationSegment(
  seg: Extract<NoteCitationSegment, { type: "cite" }>,
  key: string,
  noteTitleByPath?: ReadonlyMap<string, string>,
) {
  const noteHref = resolveNoteCitationHref(seg.href);
  if (!noteHref) return null;

  const { label, fullTitle } = resolveNoteCitationChipLabel(seg.href, seg.title, noteTitleByPath);

  return (
    <span key={key} className="chat-citation-inline">
      <ChatCitationChip href={noteHref} label={label} title={fullTitle} />
    </span>
  );
}

function renderMarkdownLink(
  href: string | undefined,
  children: React.ReactNode,
  webCites: WebCite[] | undefined,
  key: string,
  noteTitleByPath?: ReadonlyMap<string, string>,
) {
  if (href && resolveWebCitationHref(href) !== null) {
    return renderWebCitationLink(href, webCites, key);
  }
  if (href && isNoteCitationHref(href)) {
    return renderCitationSegment(
      { type: "cite", title: String(children), href },
      key,
      noteTitleByPath,
    );
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
}

function MarkdownInline({
  text,
  webCites,
  noteTitleByPath,
}: {
  text: string;
  webCites?: WebCite[];
  noteTitleByPath?: ReadonlyMap<string, string>;
}) {
  if (!text.trim()) return null;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={allowNoteUrls}
      components={{
        p: ({ children }) => <span className="chat-markdown-inline">{children}</span>,
        a: ({ href, children }) =>
          renderMarkdownLink(href, children, webCites, href ?? "link", noteTitleByPath),
        strong: ({ children }) => <strong className="chat-markdown-strong">{children}</strong>,
        em: ({ children }) => <em className="chat-markdown-em">{children}</em>,
        code: ({ children }) => <code className="chat-markdown-code">{children}</code>,
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function MarkdownBlock({
  text,
  webCites,
  noteTitleByPath,
}: {
  text: string;
  webCites?: WebCite[];
  noteTitleByPath?: ReadonlyMap<string, string>;
}) {
  if (!text.trim()) return null;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={allowNoteUrls}
      components={{
        a: ({ href, children }) =>
          renderMarkdownLink(href, children, webCites, href ?? "link", noteTitleByPath),
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

function renderParagraphSegments(
  paragraph: string,
  keyPrefix: string,
  webCites?: WebCite[],
  noteTitleByPath?: ReadonlyMap<string, string>,
): ReactNode {
  const segments = splitNoteCitationSegments(paragraph);
  const firstCiteIdx = segments.findIndex((seg) => seg.type === "cite");

  if (firstCiteIdx < 0) {
    return (
      <MarkdownBlock
        key={keyPrefix}
        text={paragraph}
        webCites={webCites}
        noteTitleByPath={noteTitleByPath}
      />
    );
  }

  const bodySegments = segments.slice(0, firstCiteIdx);
  const citeSegments = segments
    .slice(firstCiteIdx)
    .filter((seg): seg is Extract<NoteCitationSegment, { type: "cite" }> => seg.type === "cite");

  return (
    <p key={keyPrefix} className="chat-markdown-p">
      {bodySegments.map((seg, index) => {
        if (seg.type !== "text") return null;
        return (
          <MarkdownInline
            key={`${keyPrefix}-text-${index}`}
            text={seg.text}
            webCites={webCites}
            noteTitleByPath={noteTitleByPath}
          />
        );
      })}
      {citeSegments.length > 0 ? (
        <>
          {bodySegments.some((seg) => seg.type === "text" && seg.text.trim()) ? " " : null}
          <span className="chat-citation-group">
            {citeSegments.map((seg, index) =>
              renderCitationSegment(seg, `${keyPrefix}-cite-${index}`, noteTitleByPath),
            )}
          </span>
        </>
      ) : null}
    </p>
  );
}

export default function ChatMarkdown({
  text,
  className,
  validNotePaths,
  noteTitleByPath,
  webCites,
}: Props) {
  const prepared = prepareNoteCitationsForDisplay(text, validNotePaths, noteTitleByPath);
  const displayText = prepareWebCitationsForDisplay(prepared, webCites);
  if (!displayText.trim() && (!webCites || webCites.length === 0)) return null;

  const blocks = displayText.split(/\n{2,}/);

  return (
    <div className={`chat-markdown${className ? ` ${className}` : ""}`}>
      {blocks.map((block, index) =>
        renderParagraphSegments(block, `block-${index}`, webCites, noteTitleByPath),
      )}
    </div>
  );
}
