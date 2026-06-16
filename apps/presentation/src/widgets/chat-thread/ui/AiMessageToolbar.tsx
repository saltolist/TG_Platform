"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ContextMenu, type CtxMenuItem } from "@/shared/ui/context-menu";
function IcCopy() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M6 16H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function IcReload() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  );
}

function IcThumbUp() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-10a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  );
}

function IcThumbDown() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M17 14V3" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  );
}

function IcMore() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <circle cx="5" cy="12" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="19" cy="12" r="2" />
    </svg>
  );
}

function IcMenuTrash() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" x2="10" y1="11" y2="17" />
      <line x1="14" x2="14" y1="11" y2="17" />
    </svg>
  );
}

function IcMenuSources() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
      <line x1="8" x2="16" y1="7" y2="7" />
      <line x1="8" x2="14" y1="11" y2="11" />
    </svg>
  );
}

function IcMenuSpeak() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M11 5 6 9H3v6h3l5 4V5Z" />
      <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
      <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
    </svg>
  );
}

async function copyPlainText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function readAloud(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ru-RU";
  window.speechSynthesis.speak(u);
}

export default function AiMessageToolbar({
  plainText,
  onDelete,
}: {
  plainText: string;
  /** Удалить сообщение из истории чата (пункт меню «Удалить»). */
  onDelete?: () => void;
}) {
  const [vote, setVote] = useState<null | "up" | "down">(null);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

  const onCopy = useCallback(async () => {
    const ok = await copyPlainText(plainText);
    if (!ok) return;
    if (copyTimer.current) clearTimeout(copyTimer.current);
    setCopied(true);
    copyTimer.current = setTimeout(() => {
      setCopied(false);
      copyTimer.current = null;
    }, 2000);
  }, [plainText]);

  const moreItems: CtxMenuItem[] = [
    ...(onDelete
      ? [
          {
            icon: <IcMenuTrash />,
            label: "Удалить",
            danger: true as const,
            onClick: onDelete,
          } satisfies CtxMenuItem,
        ]
      : []),
    {
      icon: <IcMenuSources />,
      label: "Посмотреть источники",
      onClick: () => {},
    },
    {
      icon: <IcMenuSpeak />,
      label: "Прочесть вслух",
      onClick: () => readAloud(plainText),
    },
  ];

  return (
    <div className="ai-msg-toolbar">
      <button
        type="button"
        className={`ai-msg-action-btn${copied ? " on" : ""}`}
        aria-label={copied ? "Скопировано" : "Скопировать"}
        title={copied ? "Скопировано" : "Скопировать"}
        onClick={() => void onCopy()}
      >
        {copied ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M20 6 9 17l-5-5" />
          </svg>
        ) : (
          <IcCopy />
        )}
      </button>
      <button
        type="button"
        className="ai-msg-action-btn"
        aria-label="Перезагрузить ответ"
        title="Перезагрузить ответ"
        onClick={() => {}}
      >
        <IcReload />
      </button>
      <button
        type="button"
        className={`ai-msg-action-btn${vote === "up" ? " on" : ""}`}
        aria-label="Нравится"
        title="Нравится"
        onClick={() => setVote((v) => (v === "up" ? null : "up"))}
      >
        <IcThumbUp />
      </button>
      <button
        type="button"
        className={`ai-msg-action-btn${vote === "down" ? " on" : ""}`}
        aria-label="Не нравится"
        title="Не нравится"
        onClick={() => setVote((v) => (v === "down" ? null : "down"))}
      >
        <IcThumbDown />
      </button>
      <ContextMenu
        className="ai-msg-more-wrap"
        portal
        align="right"
        items={moreItems}
        trigger={<IcMore />}
      />
    </div>
  );
}
