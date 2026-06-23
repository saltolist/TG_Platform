"use client";

import { useRef, useState } from "react";
import { IcUserCopied, IcUserCopy } from "@/entities/message";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import {
  copyTextToClipboard,
  copyTextToClipboardFromPromise,
} from "@/shared/lib/clipboard/copyToClipboard";
import { isApiKeyPreview, isCopyableApiKey } from "@/shared/lib/profile/maskedApiKey";
import { reportMutationError } from "@/shared/ui/toast";

type Props = {
  /** Current value from state (may be preview token after GET). */
  value: string;
  /** Backend field name, e.g. "apiHash" or "botApiToken". */
  field: string;
  disabled?: boolean;
  ariaLabel?: string;
};

export default function TelegramSecretCopyButton({
  value,
  field,
  disabled = false,
  ariaLabel,
}: Props) {
  const { profile } = useRepositories();
  const [copied, setCopied] = useState(false);
  const [copying, setCopying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const markCopied = () => {
    if (timer.current) clearTimeout(timer.current);
    setCopied(true);
    timer.current = setTimeout(() => {
      setCopied(false);
      timer.current = null;
    }, 1500);
  };

  const handleCopy = () => {
    const trimmed = value.trim();
    if (!trimmed || copying || disabled) return;
    setCopying(true);

    const finish = (ok: boolean) => {
      setCopying(false);
      if (!ok) {
        reportMutationError(
          new Error("clipboard write failed"),
          "Не удалось скопировать",
        );
        return;
      }
      markCopied();
    };

    if (isCopyableApiKey(trimmed)) {
      void copyTextToClipboard(trimmed).then(finish);
      return;
    }

    if (isApiKeyPreview(trimmed)) {
      void copyTextToClipboardFromPromise(() =>
        profile.revealTelegramSecret(field).then((res) => res.value),
      )
        .then(finish)
        .catch((error) => {
          setCopying(false);
          reportMutationError(error, "Не удалось скопировать");
        });
      return;
    }

    setCopying(false);
  };

  const label = ariaLabel ?? (copied ? "Скопировано" : "Скопировать");

  return (
    <button
      type="button"
      className="profile-api-key-toggle"
      disabled={disabled || copying || !value.trim()}
      aria-label={label}
      title={label}
      onClick={handleCopy}
    >
      {copied ? <IcUserCopied /> : <IcUserCopy />}
    </button>
  );
}
