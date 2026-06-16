"use client";

import UserEmailCodeInput from "@/widgets/profile-settings/ui/user/UserEmailCodeInput";
import { TelegramResendCode } from "@/widgets/profile-settings/ui/telegram/TelegramInputs";

type Props = {
  emailCode: string;
  resendCooldownSec: number;
  onEmailCodeChange: (value: string) => void;
  onConfirm: () => void;
  onDismiss: () => void;
  onResend: () => void;
};

export default function UserEmailCodeStep({
  emailCode,
  resendCooldownSec,
  onEmailCodeChange,
  onConfirm,
  onDismiss,
  onResend,
}: Props) {
  return (
    <div className="profile-row profile-user-code-row">
      <div className="telegram-code-block telegram-desktop-code-block profile-user-code-block">
        <div className="telegram-inline-field-row telegram-desktop-code-inline profile-user-code-inline">
          <UserEmailCodeInput value={emailCode} onChange={onEmailCodeChange} onDismiss={onDismiss} />
          <button type="button" className="btn btn-ghost telegram-inline-button" onClick={onConfirm}>
            Подтвердить
          </button>
        </div>
        <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResend} />
      </div>
    </div>
  );
}
