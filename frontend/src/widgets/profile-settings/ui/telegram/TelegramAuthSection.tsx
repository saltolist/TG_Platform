"use client";

import {
  TelegramCodeInput,
  TelegramPasswordInput,
  TelegramPhoneInput,
  TelegramResendCode,
} from "@/widgets/profile-settings/ui/telegram/TelegramInputs";
import type { TelegramProfileConfig } from "@/shared/types";

type Props = {
  cfg: TelegramProfileConfig;
  codeHidden: boolean;
  awaitingPassword: boolean;
  code: string;
  password: string;
  resendCooldownSec: number;
  sendCodeDisabled: boolean;
  verifyingCode: boolean;
  verifyingPassword: boolean;
  onPhoneChange: (phone: string) => void;
  onCodeChange: (code: string) => void;
  onPasswordChange: (password: string) => void;
  onStartAuth: () => void;
  onConfirmCode: () => void;
  onConfirmPassword: () => void;
  onCancelCodeEntry: () => void;
  onResendCode: () => void;
};

export default function TelegramAuthSection({
  cfg,
  codeHidden,
  awaitingPassword,
  code,
  password,
  resendCooldownSec,
  sendCodeDisabled,
  verifyingCode,
  verifyingPassword,
  onPhoneChange,
  onCodeChange,
  onPasswordChange,
  onStartAuth,
  onConfirmCode,
  onConfirmPassword,
  onCancelCodeEntry,
  onResendCode,
}: Props) {
  const confirmStep = awaitingPassword ? (
    <TelegramPasswordInput
      value={password}
      onChange={onPasswordChange}
      onDismiss={onCancelCodeEntry}
      disabled={verifyingPassword}
    />
  ) : (
    <TelegramCodeInput
      value={code}
      onChange={onCodeChange}
      onDismiss={onCancelCodeEntry}
      disabled={verifyingCode}
    />
  );
  const confirmDisabled = awaitingPassword
    ? !password.trim() || verifyingPassword
    : !code.trim() || verifyingCode;
  const onConfirmStep = awaitingPassword ? onConfirmPassword : onConfirmCode;

  return (
    <>
      <div className="telegram-auth-desktop">
        {codeHidden ? (
          <div className="profile-row telegram-phone-desktop-row">
            <div className="profile-label">Телефон аккаунта</div>
            <div className="telegram-desktop-auth-row">
              <TelegramPhoneInput
                className="telegram-desktop-phone-input"
                value={cfg.phone}
                onChange={onPhoneChange}
              />
              <button
                className="btn btn-ghost telegram-inline-button"
                disabled={sendCodeDisabled}
                onClick={onStartAuth}
                type="button"
              >
                Отправить код
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="telegram-desktop-auth-wide">
              <div className="profile-row telegram-phone-desktop-row telegram-phone-desktop-row--code-sent">
                <div className="profile-label">Телефон аккаунта</div>
                <div className="telegram-desktop-auth-row telegram-desktop-auth-row--code-sent">
                  <TelegramPhoneInput
                    className="telegram-desktop-phone-input"
                    value={cfg.phone}
                    onChange={onPhoneChange}
                  />
                  {confirmStep}
                  <button
                    className="btn btn-ghost telegram-inline-button"
                    disabled={confirmDisabled}
                    onClick={onConfirmStep}
                    type="button"
                  >
                    Подтвердить
                  </button>
                  {awaitingPassword ? null : (
                    <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResendCode} />
                  )}
                </div>
              </div>
            </div>
            <div className="telegram-desktop-auth-narrow">
              <div className="profile-row telegram-phone-desktop-row telegram-phone-desktop-row--code-sent">
                <div className="profile-label">Телефон аккаунта</div>
                <div className="telegram-desktop-auth-row telegram-desktop-auth-row--stacked">
                  <TelegramPhoneInput
                    className="telegram-desktop-phone-input"
                    value={cfg.phone}
                    onChange={onPhoneChange}
                  />
                  <button
                    className="btn btn-ghost telegram-inline-button"
                    disabled
                    onClick={onStartAuth}
                    type="button"
                  >
                    Отправить код
                  </button>
                </div>
              </div>
              <div className="profile-row telegram-code-desktop-row">
                <div className="profile-label" aria-hidden>
                  &nbsp;
                </div>
                <div className="telegram-code-block telegram-desktop-code-block">
                  <div className="telegram-inline-field-row telegram-desktop-code-inline">
                    {confirmStep}
                    <button
                      className="btn btn-ghost telegram-inline-button"
                      disabled={confirmDisabled}
                      onClick={onConfirmStep}
                      type="button"
                    >
                      Подтвердить
                    </button>
                  </div>
                  {awaitingPassword ? null : (
                    <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResendCode} />
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="telegram-auth-mobile">
        <div className="profile-row telegram-phone-row">
          <div className="profile-label">Телефон аккаунта</div>
          <div className="telegram-inline-field-row">
            <TelegramPhoneInput value={cfg.phone} onChange={onPhoneChange} />
            <button
              className="btn btn-ghost telegram-inline-button"
              disabled={sendCodeDisabled}
              onClick={onStartAuth}
              type="button"
            >
              Отправить код
            </button>
          </div>
        </div>
        {codeHidden ? null : (
          <div className="profile-row telegram-code-action-row">
            <div className="profile-label" aria-hidden>
              &nbsp;
            </div>
            <div className="telegram-code-block">
              <div className="telegram-inline-field-row">
                {confirmStep}
                <button
                  className="btn btn-ghost telegram-inline-button"
                  disabled={confirmDisabled}
                  onClick={onConfirmStep}
                  type="button"
                >
                  Подтвердить
                </button>
              </div>
              {awaitingPassword ? null : (
                <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResendCode} />
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
