"use client";

import Lottie from "lottie-react";
import { useCallback, useEffect, useState } from "react";

import {
  EmojiPreviewError,
  fetchEmojiPreview,
  type EmojiPreviewResult,
} from "@/shared/lib/telegram/emojiPreviewClient";

type Props = {
  documentId: string;
  alt?: string;
  className?: string;
  size?: number;
};

const MAX_AUTO_RETRIES = 3;
const RETRY_DELAY_MS = 1500;

export function CustomEmojiPreview({
  documentId,
  alt = "⭐",
  className = "tg-custom-emoji",
  size = 24,
}: Props) {
  const [preview, setPreview] = useState<EmojiPreviewResult | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    setPreview(null);
    setFailed(false);

    void fetchEmojiPreview(documentId)
      .then((result) => {
        if (cancelled) return;
        setPreview(result);
        setFailed(false);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const permanent = error instanceof EmojiPreviewError && error.permanent;
        if (!permanent && attempt < MAX_AUTO_RETRIES) {
          retryTimer = setTimeout(
            () => setAttempt((value) => value + 1),
            RETRY_DELAY_MS * (attempt + 1),
          );
        } else {
          setFailed(true);
        }
      });

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [documentId, attempt]);

  const retryNow = useCallback(() => {
    setFailed(false);
    setAttempt(0);
  }, []);

  if (failed) {
    return (
      <button
        type="button"
        className={`${className} tg-custom-emoji-fallback tg-custom-emoji--failed`}
        title={`${alt} — нажмите, чтобы повторить`}
        aria-label={`${alt}: не загрузилось, повторить`}
        style={{ width: size, height: size }}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          retryNow();
        }}
      >
        ↻
      </button>
    );
  }

  if (!preview) {
    return (
      <span
        className={`${className} tg-custom-emoji-fallback tg-custom-emoji--loading`}
        title={`Загрузка: ${alt}`}
        style={{ width: size, height: size }}
        aria-label={`Загрузка ${alt}`}
      >
        ◌
      </span>
    );
  }

  if (preview.kind === "lottie") {
    return (
      <Lottie
        className={className}
        animationData={preview.data}
        loop
        autoplay
        style={{ width: size, height: size }}
      />
    );
  }

  if (preview.kind === "video") {
    return (
      <video
        className={className}
        src={preview.url}
        autoPlay
        loop
        muted
        playsInline
        width={size}
        height={size}
        aria-label={alt}
      />
    );
  }

  return (
    <img
      className={className}
      src={preview.url}
      alt={alt}
      width={size}
      height={size}
      draggable={false}
    />
  );
}
