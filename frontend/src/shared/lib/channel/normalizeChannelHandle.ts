/** Strip `@`/`t.me/` prefixes from a public channel username (not invite links or ids). */
export function normalizeChannelHandle(raw: string): string {
  const trimmed = raw.trim();
  if (isInviteLink(trimmed) || isNumericChannelId(trimmed)) {
    return trimmed;
  }
  const withoutLink = trimmed.replace(/^https?:\/\/t\.me\//i, "").replace(/^t\.me\//i, "");
  return withoutLink.replace(/^@/, "").replace(/\/$/, "");
}

export function isInviteLink(raw: string): boolean {
  return /^https?:\/\/(?:t\.me|telegram\.me)\/(?:\+|joinchat\/)/i.test(raw.trim())
    || /^(?:t\.me|telegram\.me)\/(?:\+|joinchat\/)/i.test(raw.trim());
}

export function isNumericChannelId(raw: string): boolean {
  return /^-?\d+$/.test(raw.trim());
}

/** Human-readable label for the connected-channel card (title only, no invite/id). */
export function getConnectedChannelDisplayName(
  channelTitle: string,
  channel: string,
): string {
  const title = channelTitle.trim();
  if (title && !isInviteLink(title) && !isNumericChannelId(title)) {
    return title;
  }
  const handle = channel.trim();
  if (handle.startsWith("@")) return handle;
  return title && !isInviteLink(title) ? title : "Telegram канал";
}

/** Value stored in ``TelegramProfileConfig.channel`` after a successful connect. */
export function formatConnectedChannelDisplay(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return trimmed;
  if (isInviteLink(trimmed)) {
    return trimmed.replace(/^http:\/\//i, "https://");
  }
  if (isNumericChannelId(trimmed)) {
    return trimmed;
  }
  const handle = normalizeChannelHandle(trimmed);
  return handle ? `@${handle}` : trimmed;
}
