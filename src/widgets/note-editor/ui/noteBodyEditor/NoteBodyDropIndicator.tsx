"use client";

type Props = { axis: "horizontal" | "vertical" };

export default function NoteBodyDropIndicator({ axis }: Props) {
  return (
    <div
      className={`note-embed-drop-indicator note-embed-drop-indicator--${axis}`}
      aria-hidden
    />
  );
}
