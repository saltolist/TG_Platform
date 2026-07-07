type IconProps = {
  size?: number | string;
  strokeWidth?: number;
  className?: string;
};

/** Outline smiley — same visual language as Telegram / WhatsApp emoji triggers. */
export function ComposerEmojiIcon({
  size = 25,
  strokeWidth = 1.5,
  className,
}: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden
    >
      <circle cx="12" cy="12" r="9.25" stroke="currentColor" strokeWidth={strokeWidth} />
      <circle cx="9" cy="10" r="1.1" fill="currentColor" />
      <circle cx="15" cy="10" r="1.1" fill="currentColor" />
      <path
        d="M8.5 14.25c1.15 1.65 5.85 1.65 7 0"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
