"use client";

import { useEffect, useRef, useState, type PointerEvent, type SyntheticEvent } from "react";
import { mediaKind, resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

const PROGRESS_RADIUS = 47;
const PROGRESS_CIRCUMFERENCE = 2 * Math.PI * PROGRESS_RADIUS;
const SCRUB_RING_INNER = 0.72;

function isSquareVideo(video: HTMLVideoElement): boolean {
  const { videoWidth, videoHeight } = video;
  if (!videoWidth || !videoHeight) return false;
  return Math.abs(videoWidth - videoHeight) <= 8;
}

function fractionFromPointer(clientX: number, clientY: number, rect: DOMRect): number {
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = clientX - cx;
  const dy = clientY - cy;
  let angle = Math.atan2(dx, -dy);
  if (angle < 0) angle += 2 * Math.PI;
  return angle / (2 * Math.PI);
}

function pointerDistanceNorm(clientX: number, clientY: number, rect: DOMRect): number {
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = clientX - cx;
  const dy = clientY - cy;
  const radius = Math.min(rect.width, rect.height) / 2;
  if (radius <= 0) return 0;
  return Math.sqrt(dx * dx + dy * dy) / radius;
}

export function VideoNoteMedia({ media }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const scrubbingRef = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const kind = mediaKind(media);
  const [circleMode, setCircleMode] = useState(kind === "video_note");
  const src = resolveMediaUrl(media.url);

  useEffect(() => {
    if (!playing) return;
    const video = videoRef.current;
    if (!video) return;

    let frame = 0;
    const tick = () => {
      if (video.duration > 0) {
        setProgress(video.currentTime / video.duration);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  if (!src) return null;

  const syncProgress = () => {
    const video = videoRef.current;
    if (!video || video.duration <= 0) return;
    setProgress(video.currentTime / video.duration);
  };

  const onLoadedMetadata = (event: SyntheticEvent<HTMLVideoElement>) => {
    if (kind === "video_note") {
      setCircleMode(true);
    } else {
      setCircleMode(isSquareVideo(event.currentTarget));
    }
    syncProgress();
  };

  const toggle = () => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) {
      void el.play();
      setPlaying(true);
      return;
    }
    el.pause();
    setPlaying(false);
  };

  const seekToFraction = (fraction: number) => {
    const el = videoRef.current;
    if (!el || !Number.isFinite(el.duration) || el.duration <= 0) return;
    const clamped = Math.min(Math.max(fraction, 0), 1);
    el.currentTime = clamped * el.duration;
    setProgress(clamped);
  };

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    scrubbingRef.current = false;
    const rect = event.currentTarget.getBoundingClientRect();
    if (pointerDistanceNorm(event.clientX, event.clientY, rect) < SCRUB_RING_INNER) {
      return;
    }
    scrubbingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    seekToFraction(fractionFromPointer(event.clientX, event.clientY, rect));
  };

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (!scrubbingRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    seekToFraction(fractionFromPointer(event.clientX, event.clientY, rect));
  };

  const onPointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    if (scrubbingRef.current) {
      scrubbingRef.current = false;
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        // Pointer was already released.
      }
      return;
    }
    toggle();
  };

  const showProgress = playing || progress > 0.001;

  if (!circleMode) {
    return (
      <video
        ref={videoRef}
        className="tg-media-video"
        src={src}
        controls
        preload="metadata"
        playsInline
        onLoadedMetadata={onLoadedMetadata}
      />
    );
  }

  return (
    <div className="tg-media-compact-slot tg-media-compact-slot--video-note">
      <button
        type="button"
        className="tg-media-video-note-hit"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        aria-label={playing ? "Пауза" : "Воспроизвести"}
      >
        <video
          ref={videoRef}
          className="tg-media-video-note"
          src={src}
          playsInline
          preload="metadata"
          onLoadedMetadata={onLoadedMetadata}
          onTimeUpdate={syncProgress}
          onEnded={() => {
            setPlaying(false);
            setProgress(0);
          }}
          onPause={() => setPlaying(false)}
          onPlay={() => setPlaying(true)}
        />
        {showProgress ? (
          <svg className="tg-media-video-note-progress" viewBox="0 0 100 100" aria-hidden>
            <circle className="tg-media-video-note-progress-track" cx="50" cy="50" r={PROGRESS_RADIUS} />
            <circle
              className="tg-media-video-note-progress-ring"
              cx="50"
              cy="50"
              r={PROGRESS_RADIUS}
              strokeDasharray={`${progress * PROGRESS_CIRCUMFERENCE} ${PROGRESS_CIRCUMFERENCE}`}
              transform="rotate(-90 50 50)"
            />
          </svg>
        ) : null}
        {!playing ? <span className="tg-media-video-note-play" aria-hidden /> : null}
      </button>
    </div>
  );
}
