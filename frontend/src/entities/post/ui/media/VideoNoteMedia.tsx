"use client";

import { useRef, useState, type SyntheticEvent } from "react";
import { mediaKind, resolveMediaUrl } from "@/shared/lib/helpers";
import type { PostMedia } from "@/shared/types";

type Props = {
  media: PostMedia;
};

function isSquareVideo(video: HTMLVideoElement): boolean {
  const { videoWidth, videoHeight } = video;
  if (!videoWidth || !videoHeight) return false;
  return Math.abs(videoWidth - videoHeight) <= 8;
}

export function VideoNoteMedia({ media }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const kind = mediaKind(media);
  const [circleMode, setCircleMode] = useState(kind === "video_note");
  const src = resolveMediaUrl(media.url);
  if (!src) return null;

  const onLoadedMetadata = (event: SyntheticEvent<HTMLVideoElement>) => {
    if (kind === "video_note") {
      setCircleMode(true);
      return;
    }
    setCircleMode(isSquareVideo(event.currentTarget));
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
    <button
      type="button"
      className="tg-media-video-note-hit"
      onClick={toggle}
      aria-label={playing ? "Пауза" : "Воспроизвести"}
    >
      <video
        ref={videoRef}
        className="tg-media-video-note"
        src={src}
        playsInline
        preload="metadata"
        onLoadedMetadata={onLoadedMetadata}
        onEnded={() => setPlaying(false)}
        onPause={() => setPlaying(false)}
        onPlay={() => setPlaying(true)}
      />
      {!playing ? <span className="tg-media-video-note-play" aria-hidden /> : null}
    </button>
  );
}
