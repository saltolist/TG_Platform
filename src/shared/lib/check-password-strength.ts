export const PASSWORD_REQUIREMENTS_HINT =
  "Не менее 8 символов, буквы, цифры и спецсимволы";

const COMMON_WEAK_PASSWORDS = new Set([
  "password",
  "password1",
  "12345678",
  "123456789",
  "qwertyui",
  "qwerty123",
  "пароль",
  "пароль123",
]);

export type PasswordStrengthResult = {
  isWeak: boolean;
  message: string | null;
};

export function checkPasswordStrength(password: string): PasswordStrengthResult {
  if (!password) {
    return { isWeak: false, message: null };
  }

  if (password.length < 8) {
    return { isWeak: true, message: "Минимум 8 символов" };
  }

  const hasUpper = /[A-ZА-ЯЁ]/.test(password);
  const hasLower = /[a-zа-яё]/.test(password);
  const hasDigit = /\d/.test(password);
  const hasSpecial = /[^a-zA-Zа-яА-ЯёЁ0-9]/.test(password);

  if (!hasUpper) {
    return { isWeak: true, message: "Добавьте буквы верхнего регистра" };
  }
  if (!hasLower) {
    return { isWeak: true, message: "Добавьте буквы нижнего регистра" };
  }
  if (!hasDigit) {
    return { isWeak: true, message: "Добавьте цифры" };
  }
  if (!hasSpecial) {
    return { isWeak: true, message: "Добавьте спецсимволы" };
  }

  if (COMMON_WEAK_PASSWORDS.has(password.toLowerCase())) {
    return { isWeak: true, message: "Слишком простой пароль" };
  }

  return { isWeak: false, message: null };
}
