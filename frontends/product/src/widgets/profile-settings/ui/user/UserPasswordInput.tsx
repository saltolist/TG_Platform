"use client";

import ProfileEyeIcon from "@/widgets/profile-settings/ui/ProfileEyeIcon";

type Props = {
  value: string;
  onChange: (value: string) => void;
  visible: boolean;
  onToggleVisible: () => void;
  placeholder: string;
  autoComplete: string;
  toggleLabel: string;
};

export default function UserPasswordInput({
  value,
  onChange,
  visible,
  onToggleVisible,
  placeholder,
  autoComplete,
  toggleLabel,
}: Props) {
  return (
    <div className="telegram-input-wrap profile-user-password-input-wrap">
      <input
        className="profile-input profile-input-explicit telegram-input profile-user-password-input telegram-input-with-toggle"
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="profile-api-key-toggle"
        aria-label={visible ? `Скрыть ${toggleLabel}` : `Показать ${toggleLabel}`}
        title={visible ? `Скрыть ${toggleLabel}` : `Показать ${toggleLabel}`}
        onClick={onToggleVisible}
      >
        <ProfileEyeIcon hidden={!visible} />
      </button>
    </div>
  );
}
