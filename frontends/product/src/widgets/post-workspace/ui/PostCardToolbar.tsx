"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { NoteIconEdit } from "@/shared/ui/icons/note-header-icons";

async function copyPlainText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function IcCopy() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M6 16H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function IcCopied() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

export default function PostCardToolbar({
  plainText,
  onEdit,
}: {
  plainText: string;
  onEdit: () => void;
}) {
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

  return (
    <div className="post-msg-actions" aria-label="Действия с постом">
      <div className="ai-msg-toolbar">
        <button
          type="button"
          className={`ai-msg-action-btn${copied ? " on" : ""}`}
          aria-label={copied ? "Скопировано" : "Скопировать"}
          title={copied ? "Скопировано" : "Скопировать"}
          onClick={() => void onCopy()}
        >
          {copied ? <IcCopied /> : <IcCopy />}
        </button>
        <button
          type="button"
          className="ai-msg-action-btn"
          aria-label="Редактировать"
          title="Редактировать"
          onClick={onEdit}
        >
          <NoteIconEdit size={18} />
        </button>
      </div>
    </div>
  );
}
