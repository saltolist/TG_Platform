import { ApiError } from "@/shared/api/httpClient";

type ValidationDetail = {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
};

function validationDetailMessage(details: ValidationDetail[]): string | null {
  for (const detail of details) {
    const field = detail.loc?.find((part) => typeof part === "string" && part !== "body");
    if (field === "email") return "Укажите корректный email";
    if (field === "password") return "Укажите пароль";
    if (field === "code") return "Укажите код из письма";
  }
  return null;
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof TypeError) {
    return "Не удалось связаться с сервером. Запустите docker compose up и откройте http://localhost:3000";
  }
  if (error instanceof ApiError) {
    const body = error.body as
      | { error?: string; detail?: string | ValidationDetail[]; details?: ValidationDetail[] }
      | undefined;
    if (body?.details?.length) {
      const detailMessage = validationDetailMessage(body.details);
      if (detailMessage) return detailMessage;
    }
    if (typeof body?.detail === "string" && body.detail.trim()) return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length) {
      const detailMessage = validationDetailMessage(body.detail);
      if (detailMessage) return detailMessage;
    }
    if (body?.error) return body.error;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
