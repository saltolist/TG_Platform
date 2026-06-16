type IconProps = { size?: number | string; strokeWidth?: number };

/** Толщина контура как у скрепки в `.note-header-plain-btn--sm` (22px). */
export const NOTE_HEADER_ICON_STROKE = 1.75;

/** Компенсация для `.note-header-plain-btn--mode` (24px) — визуально та же толщина, что у скрепки. */
export const NOTE_HEADER_ICON_STROKE_MODE = (NOTE_HEADER_ICON_STROKE * 22) / 24;

/** Редактирование — карандаш на линии (не диагональный PencilIcon). */
export function NoteIconEdit({ size = "100%", strokeWidth = NOTE_HEADER_ICON_STROKE }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  );
}

/** Режим просмотра (reading view, как в Obsidian) */
export function NoteIconPreview({ size = "100%", strokeWidth = NOTE_HEADER_ICON_STROKE }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 6.5C10.5 5.6 8.7 5 6 5H4.75A1.75 1.75 0 0 0 3 6.75v10.5C3 18.2 3.8 19 4.75 19H6c2.7 0 4.5.6 6 1.5" />
      <path d="M12 6.5C13.5 5.6 15.3 5 18 5h1.25A1.75 1.75 0 0 1 21 6.75v10.5c0 .95-.8 1.75-1.75 1.75H18c-2.7 0-4.5.6-6 1.5" />
      <path d="M12 6.5V20.5" />
    </svg>
  );
}

export function NoteIconAttach({ size = "100%", strokeWidth = NOTE_HEADER_ICON_STROKE }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      aria-hidden
    >
      <path
        d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function NoteIconImage({ size = 16 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="m21 15-5-5L5 21" />
    </svg>
  );
}
