import { expect, type Page } from "@playwright/test";

const LOAD_TIMEOUT = 30_000;

export async function loginAsDemo(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Основная навигация").getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Вход" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.getByLabel("Вход и регистрация").getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByRole("heading", { name: "Над чем работаем?" })).toBeVisible({ timeout: LOAD_TIMEOUT });
}
