"use client";

import UserPasswordInput from "@/widgets/profile-settings/ui/user/UserPasswordInput";
import { PASSWORD_REQUIREMENTS_HINT, type PasswordStrengthResult } from "@/shared/lib/check-password-strength";

type Props = {
  password: string;
  passwordConfirm: string;
  passwordVisible: boolean;
  passwordConfirmVisible: boolean;
  passwordStrength: PasswordStrengthResult;
  passwordsMismatch: boolean;
  canConfirm: boolean;
  onPasswordChange: (value: string) => void;
  onPasswordConfirmChange: (value: string) => void;
  onTogglePasswordVisible: () => void;
  onTogglePasswordConfirmVisible: () => void;
  onConfirm: () => void;
};

export default function UserPasswordStep({
  password,
  passwordConfirm,
  passwordVisible,
  passwordConfirmVisible,
  passwordStrength,
  passwordsMismatch,
  canConfirm,
  onPasswordChange,
  onPasswordConfirmChange,
  onTogglePasswordVisible,
  onTogglePasswordConfirmVisible,
  onConfirm,
}: Props) {
  return (
    <div className="profile-user-password-form">
      <p className="profile-user-password-requirements">{PASSWORD_REQUIREMENTS_HINT}</p>
      <div className="profile-row">
        <div className="profile-label">Новый пароль</div>
        <UserPasswordInput
          autoComplete="new-password"
          placeholder="Введите пароль"
          toggleLabel="новый пароль"
          value={password}
          visible={passwordVisible}
          onChange={onPasswordChange}
          onToggleVisible={onTogglePasswordVisible}
        />
      </div>
      {passwordStrength.message ? (
        <p className="profile-user-password-hint" role="alert">
          {passwordStrength.message}
        </p>
      ) : null}
      <div className="profile-row">
        <div className="profile-label">Повтор пароля</div>
        <UserPasswordInput
          autoComplete="new-password"
          placeholder="Повторите пароль"
          toggleLabel="повтор пароля"
          value={passwordConfirm}
          visible={passwordConfirmVisible}
          onChange={onPasswordConfirmChange}
          onToggleVisible={onTogglePasswordConfirmVisible}
        />
      </div>
      {passwordsMismatch ? (
        <p className="profile-user-password-hint" role="alert">
          Пароли не совпадают
        </p>
      ) : null}
      <div className="profile-action-buttons profile-action-buttons--ai profile-user-password-confirm">
        <button
          type="button"
          className="btn btn-ghost telegram-inline-button"
          disabled={!canConfirm}
          onClick={onConfirm}
        >
          Подтвердить
        </button>
      </div>
    </div>
  );
}
