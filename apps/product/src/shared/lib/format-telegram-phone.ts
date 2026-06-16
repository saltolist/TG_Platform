const PHONE_DIGIT_LIMIT = 11;

/** Длина отформатированного номера: +7 999 000-00-00 */
export const TELEGRAM_PHONE_FORMATTED_MAX_LENGTH = 16;

export function countTelegramPhoneDigits(phone: string): number {
  return phone.replace(/\D/g, "").length;
}

export function isTelegramPhoneComplete(phone: string): boolean {
  return countTelegramPhoneDigits(phone) >= PHONE_DIGIT_LIMIT;
}

export function formatTelegramPhoneInput(raw: string): string {
  if (!raw) return "";

  let digits = raw.replace(/\D/g, "");

  if (digits.length === 0) {
    return raw.includes("+") ? "+" : "";
  }

  if (digits.startsWith("8")) {
    digits = `7${digits.slice(1)}`;
  } else if (!digits.startsWith("7")) {
    digits = `7${digits}`;
  }

  digits = digits.slice(0, PHONE_DIGIT_LIMIT);

  return formatPhoneFromDigits(digits);
}

function formatPhoneFromDigits(digits: string): string {
  if (!digits.startsWith("7")) return "";

  const local = digits.slice(1);
  let result = "+7";

  if (local.length > 0) result += ` ${local.slice(0, 3)}`;
  if (local.length > 3) result += ` ${local.slice(3, 6)}`;
  if (local.length > 6) result += `-${local.slice(6, 8)}`;
  if (local.length > 8) result += `-${local.slice(8, 10)}`;

  return result;
}
