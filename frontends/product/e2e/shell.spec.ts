import { expect, test } from "@playwright/test";
import { loginAsDemo } from "./helpers/auth";

const LOAD_TIMEOUT = 30_000;

test.beforeEach(async ({ page }) => {
  await loginAsDemo(page);
});

test("home page loads", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Над чем работаем?")).toBeVisible({ timeout: LOAD_TIMEOUT });
});

test("home composer sends message to new gchat", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Над чем работаем?")).toBeVisible({ timeout: LOAD_TIMEOUT });
  const editor = page.getByRole("textbox", { name: /Сообщение|контент/i });
  await editor.click();
  await editor.fill("контент-план на неделю");
  await page.locator(".send-btn").click();
  await expect(page).toHaveURL(/\/gchat\/\?id=gc\d+/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByText("контент-план на неделю").first()).toBeVisible({ timeout: LOAD_TIMEOUT });
});

test("navigate feed from sidebar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Над чем работаем?")).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.locator("#nav-feed").click();
  await expect(page.getByRole("heading", { name: "Лента" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(page.getByText("Опубликованные")).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(page.getByText("Черновики")).toBeVisible();
});

test("navigate chats and back to home", async ({ page }) => {
  await page.goto("/");
  await page.goto("/chats/");
  await expect(page.getByRole("heading", { name: "Чаты" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(page.getByRole("button", { name: "Новый чат" })).toBeVisible();
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(page).toHaveURL(/\/?$/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByText("Над чем работаем?")).toBeVisible({ timeout: LOAD_TIMEOUT });
});

test("navigate notes from sidebar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Над чем работаем?")).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.locator("#nav-notes .nav-item-chats-main").click();
  await expect(page.getByRole("heading", { name: "Заметки" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(page.locator(".notes-filter-row").getByRole("button", { name: "Все" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Новая заметка" })).toBeVisible();
});

test("gchat back navigates to chats", async ({ page }) => {
  await page.goto("/gchat/?id=gc1");
  await expect(page.getByRole("navigation", { name: "Хлебные крошки" })).toContainText(
    "Анализ недели",
    { timeout: LOAD_TIMEOUT },
  );
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(page.getByRole("heading", { name: "Чаты" })).toBeVisible();
});

test("legacy gchat path redirects to query form", async ({ page }) => {
  await page.goto("/gchat/gc1/");
  await expect(page).toHaveURL(/\/gchat\/\?id=gc1/, { timeout: LOAD_TIMEOUT });
  await expect(page.getByRole("navigation", { name: "Хлебные крошки" })).toContainText(
    "Анализ недели",
    { timeout: LOAD_TIMEOUT },
  );
});

test("analytics page loads with period picker", async ({ page }) => {
  await page.goto("/analytics/");
  await expect(page.getByRole("heading", { name: "Аналитика канала" })).toBeVisible({
    timeout: LOAD_TIMEOUT,
  });
  await expect(page.getByRole("button", { name: "Период" })).toContainText("30 дн.");
  await expect(page.getByText("Динамика прироста")).toBeVisible();
});

test("post page loads", async ({ page }) => {
  await page.goto("/post/1/");
  await expect(page.getByRole("navigation", { name: "Хлебные крошки" })).toContainText(
    "Два года я не мог нажать кнопку",
    { timeout: LOAD_TIMEOUT },
  );
  await expect(page.locator("#screen-post .post-msg-card")).toBeVisible();
  await expect(page.locator("#screen-post .input-wrap")).toBeVisible();
  await expect(page.locator("#screen-post").getByRole("button", { name: "Заметки" })).toBeVisible();
});

test("legacy post notes path redirects to canonical post url", async ({ page }) => {
  await page.goto("/post/5/notes/");
  await expect(page).toHaveURL(/\/post\/5\/$/, { timeout: LOAD_TIMEOUT });
});

test("global note page loads after cache sync", async ({ page }) => {
  await page.goto("/note/global/gn1/");
  await expect(page.locator("#screen-note .note-shell")).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(
    page.getByRole("textbox", { name: "Без названия" }),
  ).toHaveValue("Структура серии про барьеры инвестора");
});

test("chats scope select can be changed", async ({ page }) => {
  await page.goto("/chats/");
  await expect(page.getByRole("heading", { name: "Чаты" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.getByRole("button", { name: "Область чатов" }).click();
  await page.locator(".ctx-item", { hasText: "Глобальные" }).click();
  await expect(page.getByRole("button", { name: "Область чатов" })).toContainText("Глобальные");
});

test("feed opens published post in chat mode", async ({ page }) => {
  await page.goto("/feed/");
  await expect(page.getByRole("heading", { name: "Лента" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.locator(".post-card").first().click();
  await expect(page).toHaveURL(/\/post\/\d+\//, { timeout: LOAD_TIMEOUT });
  await expect(page.locator("#screen-post .post-msg-card")).toBeVisible();
});

test("feed composer creates draft", async ({ page }) => {
  await page.goto("/feed/");
  await expect(page.getByRole("heading", { name: "Лента" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  const draftText = `E2E черновик ${Date.now()}`;
  await page.locator("#feed-input").fill(draftText);
  await page.locator("#screen-feed .send-btn").click();
  await expect(page.getByText(draftText)).toBeVisible({ timeout: LOAD_TIMEOUT });
});

test("feed draft opens on post screen with text", async ({ page }) => {
  await page.goto("/feed/");
  await expect(page.getByRole("heading", { name: "Лента" })).toBeVisible({ timeout: LOAD_TIMEOUT });
  const draftText = `E2E open draft ${Date.now()}`;
  await page.locator("#feed-input").fill(draftText);
  await page.locator("#screen-feed .send-btn").click();
  const draftCard = page.locator(".feed-section", { hasText: "Черновики" }).locator(".post-card", {
    hasText: draftText,
  });
  await expect(draftCard).toBeVisible({ timeout: LOAD_TIMEOUT });
  await draftCard.click();
  await expect(page).toHaveURL(/\/post\/\d+\//, { timeout: LOAD_TIMEOUT });
  await expect(page.locator("#screen-post .post-msg-card")).toContainText(draftText, {
    timeout: LOAD_TIMEOUT,
  });
});

test("post switches notes and chats modes", async ({ page }) => {
  await page.goto("/post/1/");
  await expect(page.locator("#screen-post .post-msg-card")).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.locator("#screen-post").getByRole("button", { name: "Заметки" }).click();
  await expect(page.getByRole("navigation", { name: "Хлебные крошки" })).toContainText("Заметки");
  await expect(page.getByRole("button", { name: "Новая заметка" })).toBeVisible();
  await page.locator("#screen-post").getByRole("button", { name: "Чаты" }).click();
  await expect(page.getByRole("navigation", { name: "Хлебные крошки" })).toContainText("Чаты");
  await expect(page.getByRole("button", { name: "Новый чат" })).toBeVisible();
});

test("post inline edit saves text", async ({ page }) => {
  await page.goto("/post/1/");
  await expect(page.locator("#screen-post .post-msg-card")).toBeVisible({ timeout: LOAD_TIMEOUT });
  await page.getByRole("button", { name: "Редактировать" }).click();
  const textarea = page.getByRole("textbox", { name: "Текст поста" });
  await expect(textarea).toBeVisible();
  const suffix = ` [e2e ${Date.now()}]`;
  const original = await textarea.inputValue();
  await textarea.fill(`${original}${suffix}`);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.locator(".post-msg-card")).toContainText(suffix);
});

test("post publishes draft via context menu", async ({ page }) => {
  await page.goto("/post/4/");
  await expect(page.locator("#screen-post .post-msg-card")).toBeVisible({ timeout: LOAD_TIMEOUT });
  const menuBtn = page.locator("#screen-post button").filter({ hasText: "•••" });
  await menuBtn.click();
  await page.locator(".ctx-item", { hasText: "Опубликовать" }).click();
  await menuBtn.click();
  await expect(page.locator(".ctx-item", { hasText: "Опубликовать" })).toHaveCount(0);
});
