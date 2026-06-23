"use client";

import { IcUserCopied, IcUserCopy } from "@/entities/message";

type Props = {
  copied: boolean;
  disabled?: boolean;
  onCopy: () => void;
};

export default function ProfileApiKeyCopyButton({ copied, disabled, onCopy }: Props) {
  return (
    <button
      type="button"
      className="profile-api-key-toggle"
      disabled={disabled}
      aria-label={copied ? "API key скопирован" : "Скопировать API key"}
      title={copied ? "Скопировано" : "Скопировать API key"}
      onClick={() => void onCopy()}
    >
      {copied ? <IcUserCopied /> : <IcUserCopy />}
    </button>
  );
}
