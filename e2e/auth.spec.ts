import { expect, test } from "@playwright/test";

const LOAD_TIMEOUT = 30_000;

test("presentation mode opens home without login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByRole("heading", { name: "Над чем работаем?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Войти" })).toBeVisible();
});

test("login overlay opens and closes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("dialog", { name: "Вход и регистрация" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Вход" })).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();
  await expect(page.getByRole("heading", { name: "Вход" })).not.toBeVisible();
});

test("login overlay always opens on login form after register view", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Вход и регистрация").getByRole("button", { name: "Регистрация" }).click();
  await expect(page.getByRole("heading", { name: "Регистрация" })).toBeVisible();

  await page.getByRole("button", { name: "Закрыть" }).click();
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Вход" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Регистрация" })).not.toBeVisible();
});

test("demo login opens home", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Основная навигация").getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Вход и регистрация").getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByRole("heading", { name: "Над чем работаем?" })).toBeVisible();
  await expect(page.getByLabel("Основная навигация").getByRole("button", { name: "Профиль" })).toBeVisible();
});

test("logout returns to presentation home", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Основная навигация").getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Вход и регистрация").getByRole("button", { name: "Войти" }).click();
  await expect(page.getByLabel("Основная навигация").getByRole("button", { name: "Профиль" })).toBeVisible();

  await page.getByLabel("Основная навигация").getByRole("button", { name: "Профиль" }).click();
  await page.getByRole("button", { name: "Выйти" }).click();

  await expect(page).toHaveURL(/\/$/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByRole("button", { name: "Войти" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Над чем работаем?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Вход" })).not.toBeVisible();
});
