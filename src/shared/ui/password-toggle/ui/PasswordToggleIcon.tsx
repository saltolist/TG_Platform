"use client";

type Props = { hidden: boolean; className?: string };

export default function PasswordToggleIcon({
  hidden,
  className = "profile-api-key-toggle-icon",
}: Props) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" />
      <circle cx="12" cy="12" r="2.6" />
      {hidden ? <path d="M4 4l16 16" /> : null}
    </svg>
  );
}
