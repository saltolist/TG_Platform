import type { ReactNode } from "react";

type IconProps = { size?: number; strokeWidth?: number };

const S = 18;

function MenuSvg({ size = S, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

/** Новый чат / новая заметка */
export function MenuIconPlus({ size = 18, strokeWidth = 2.625 }: IconProps) {
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
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

/** Учитывать в ИИ */
export function MenuIconBrain({ size = S }: IconProps) {
  return (
    <MenuSvg size={size}>
      <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z" />
      <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z" />
    </MenuSvg>
  );
}

const MENU_BRAIN_STRIKE_LEN_PX = 24;

/** Не учитывать в ИИ */
export function MenuIconBrainOff({ size = S }: IconProps) {
  const half = (MENU_BRAIN_STRIKE_LEN_PX / 2) * (24 / size);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <g strokeWidth={1.8}>
        <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z" />
        <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z" />
      </g>
      <g transform="translate(12 12) rotate(45)">
        <line x1={-half} y1={0} x2={half} y2={0} strokeWidth={1.5} />
      </g>
    </svg>
  );
}

/** Опубликовать */
export function MenuIconPublish({ size = S }: IconProps) {
  return (
    <MenuSvg size={size}>
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M5 20h14" />
    </MenuSvg>
  );
}

/** Запланировать */
export function MenuIconClock({ size = S }: IconProps) {
  return (
    <MenuSvg size={size}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.5 2" />
    </MenuSvg>
  );
}

/** Отменить публикацию */
export function MenuIconCancel({ size = S }: IconProps) {
  return (
    <MenuSvg size={size}>
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </MenuSvg>
  );
}

/** Удалить */
export function MenuIconTrash({ size = S }: IconProps) {
  return (
    <MenuSvg size={size}>
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" x2="10" y1="11" y2="17" />
      <line x1="14" x2="14" y1="11" y2="17" />
    </MenuSvg>
  );
}
