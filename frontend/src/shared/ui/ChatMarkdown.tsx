"use client";

import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  citationChipLabel,
  isNoteCitationHref,
  resolveNoteCitationHref,
} from "@/shared/lib/noteCitation";
import ChatCitationChip from "@/shared/ui/ChatCitationChip";

type Props = {
  text: string;
  className?: string;
};

function allowNoteUrls(url: string): string {
  if (isNoteCitationHref(url)) return url;
  return defaultUrlTransform(url);
}

function linkChildrenToText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(linkChildrenToText).join("");
  if (children && typeof children === "object" && "props" in children) {
    const nested = (children as { props?: { children?: ReactNode } }).props?.children;
    return nested != null ? linkChildrenToText(nested) : "";
  }
  return "";
}

function ChatMarkdownLink({ href, children }: { href?: string; children?: ReactNode }) {
  if (!href) return <span>{children}</span>;

  const noteHref = resolveNoteCitationHref(href);
  if (noteHref) {
    const rawTitle = linkChildrenToText(children);
    const label = citationChipLabel(rawTitle);
    const fullTitle = rawTitle.trim() || undefined;
    return <ChatCitationChip href={noteHref} label={label} title={fullTitle} />;
  }

  if (href.startsWith("/") || href.startsWith("http://") || href.startsWith("https://")) {
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

export default function ChatMarkdown({ text, className }: Props) {
  if (!text.trim()) return null;

  return (
    <div className={`chat-markdown${className ? ` ${className}` : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={allowNoteUrls}
        components={{
          a: ({ href, children }) => <ChatMarkdownLink href={href}>{children}</ChatMarkdownLink>,
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
    </div>
  );
}
