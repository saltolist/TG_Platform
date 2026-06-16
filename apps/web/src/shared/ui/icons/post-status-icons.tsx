type IconProps = { size?: number | string };

export function PencilIcon({ size = "100%" }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <g
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        transform="translate(12 12) scale(1.12) translate(-12 -12) rotate(-45 12 12)"
      >
        <path d="M3 12 L6.5 9.5 L6.5 14.5Z" fill="none" strokeWidth="1.75" />
        <path d="M6.5 9.5 H16.5 L18.6 9.5 Q21.2 12 18.6 14.5 H6.5" strokeWidth="1.75" />
        <path d="M16.5 9.5 V14.5" strokeWidth="1.75" />
      </g>
    </svg>
  );
}

export function CheckIcon({ size = "100%" }: IconProps) {
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
      <path d="M4.75 13.25 9.25 17.75 19.25 6.25" />
    </svg>
  );
}

export function ClockIcon({ size = "100%" }: IconProps) {
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
      <g transform="translate(0 -1)">
        <circle cx="12" cy="12" r="8.25" />
        <path d="M12 7.75V12l3.25 2.25" />
      </g>
    </svg>
  );
}
