export const DEFAULT_USER = {
  nick: "researcher",
  email: "user@tgplatform.local",
} as const;

export type UserPasswordFlow = "idle" | "confirm-send" | "code" | "password";
