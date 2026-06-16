"use client";

import {
  TelegramCodeInput,
  TelegramPhoneInput,
  TelegramResendCode,
} from "@/widgets/profile-settings/ui/telegram/TelegramInputs";
import type { TelegramProfileConfig } from "@/shared/types";

type Props = {
  cfg: TelegramProfileConfig;
  codeHidden: boolean;
  code: string;
  resendCooldownSec: number;
  sendCodeDisabled: boolean;
  onPhoneChange: (phone: string) => void;
  onCodeChange: (code: string) => void;
  onStartAuth: () => void;
  onConfirmCode: () => void;
  onCancelCodeEntry: () => void;
  onResendCode: () => void;
};

export default function TelegramAuthSection({
  cfg,
  codeHidden,
  code,
  resendCooldownSec,
  sendCodeDisabled,
  onPhoneChange,
  onCodeChange,
  onStartAuth,
  onConfirmCode,
  onCancelCodeEntry,
  onResendCode,
}: Props) {
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
                  <TelegramCodeInput value={code} onChange={onCodeChange} onDismiss={onCancelCodeEntry} />
                  <button className="btn btn-ghost telegram-inline-button" onClick={onConfirmCode} type="button">
                    Подтвердить
                  </button>
                  <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResendCode} />
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
                    <TelegramCodeInput value={code} onChange={onCodeChange} onDismiss={onCancelCodeEntry} />
                    <button className="btn btn-ghost telegram-inline-button" onClick={onConfirmCode} type="button">
                      Подтвердить
                    </button>
                  </div>
                  <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResendCode} />
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
                <TelegramCodeInput value={code} onChange={onCodeChange} onDismiss={onCancelCodeEntry} />
                <button className="btn btn-ghost telegram-inline-button" onClick={onConfirmCode} type="button">
                  Подтвердить
                </button>
              </div>
              <TelegramResendCode secondsLeft={resendCooldownSec} onResend={onResendCode} />
            </div>
          </div>
        )}
      </div>
    </>
  );
}
