type Props = {
  className?: string;
};

export function PostTelegramSyncLabel({ className }: Props) {
  return (
    <span
      className={["post-telegram-sync-label", className].filter(Boolean).join(" ")}
      role="status"
      aria-live="polite"
    >
      Синхронизация с Telegram
    </span>
  );
}
