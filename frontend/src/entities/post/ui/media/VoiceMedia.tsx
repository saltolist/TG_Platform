"use client";

import { useEffect, useRef, useState } from "react";
import { resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

export function VoiceMedia({ media }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(media.durationSeconds ?? 0);
  const src = resolveMediaUrl(media.url);

  useEffect(() => {
    if (!playing) return;
    const audio = audioRef.current;
    if (!audio) return;

    let frame = 0;
    const tick = () => {
      if (audio.duration > 0) {
        setProgress(audio.currentTime / audio.duration);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  if (!src) return null;

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      return;
    }
    void audio.play();
  };

  const onLoadedMetadata = () => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(audio.duration)) return;
    setDuration(Math.round(audio.duration));
  };

  const onTimeUpdate = () => {
    const audio = audioRef.current;
    if (!audio || audio.duration <= 0) return;
    setProgress(audio.currentTime / audio.duration);
  };

  const displayDuration = playing
    ? formatDuration((duration || 0) * (1 - progress))
    : formatDuration(duration);

  return (
    <div
      className="tg-media-voice"
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <button
        type="button"
        className="tg-media-voice-play"
        onClick={toggle}
        aria-label={playing ? "Пауза" : "Воспроизвести"}
      >
        {playing ? (
          <svg viewBox="0 0 24 24" aria-hidden>
            <rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor" />
            <rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden>
            <path d="M8 5.5v13l11-6.5z" fill="currentColor" />
          </svg>
        )}
      </button>
      <div className="tg-media-voice-track" aria-hidden>
        <div className="tg-media-voice-fill" style={{ width: `${progress * 100}%` }} />
      </div>
      <span className="tg-media-voice-duration">{displayDuration}</span>
      <audio
        ref={audioRef}
        className="tg-media-voice-audio"
        src={src}
        preload="metadata"
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={onTimeUpdate}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setProgress(0);
        }}
      />
    </div>
  );
}
