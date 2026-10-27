import { expect, test } from "@playwright/test";
import { ITEM, OWNER_KEY, signIn } from "./e2e-support";

/** Logout, session-change and identity isolation. The key stays in memory only. */

async function storageSnapshot(page: import("@playwright/test").Page) {
  return page.evaluate(() => ({
    local: Object.entries(localStorage).map(([key, value]) => `${key}=${value}`),
    session: Object.entries(sessionStorage).map(([key, value]) => `${key}=${value}`),
    cookie: document.cookie,
  }));
}

test("sign-in keeps the owner key out of every durable place and uses an HttpOnly cookie", async ({ page, context }) => {
  await signIn(page);
  await page.goto("/#/queue");
  await expect(page.getByText(ITEM.first).first()).toBeVisible();
  const stored = await storageSnapshot(page);
  expect(stored.local, `localStorage was written: ${stored.local.join(", ")}`).toEqual([]);
  expect(stored.session, `sessionStorage was written: ${stored.session.join(", ")}`).toEqual([]);
  expect(stored.cookie).toBe("");
  expect(page.url()).not.toContain(OWNER_KEY);
  const html = await page.content();
  expect(html).not.toContain(OWNER_KEY);

  const session = (await context.cookies()).find((cookie) => cookie.name === "probation_owner_session");
  expect(session, "the server issued a session cookie").toBeDefined();
  expect(session?.httpOnly, "script cannot read the session id").toBe(true);
  expect(session?.sameSite).toBe("Strict");
  expect(session?.path).toBe("/api");
  expect(session?.secure).toBe(false);
});

test("after sign-out no private data survives in the DOM and the session cookie is gone", async ({ page, context }) => {
  await signIn(page);
  await page.goto("/#/queue");
  await expect(page.getByText(ITEM.first).first()).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByText(ITEM.first)).toHaveCount(0);
  await expect(page.getByText(ITEM.conflict)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Review email" })).toHaveCount(0);
  await expect(page.getByLabel("Email")).toHaveValue("");
  await expect(page.getByLabel("Password")).toHaveValue("");
  const stored = await storageSnapshot(page);
  expect(stored.local).toEqual([]);
  expect(stored.session).toEqual([]);
  await expect
    .poll(async () => (await context.cookies()).some((cookie) => cookie.name === "probation_owner_session"))
    .toBe(false);
});

test("a response still in flight cannot repopulate a closed session", async ({ page }) => {
  await signIn(page);
  await page.route("**/api/queue", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    try {
      await route.continue();
    } catch {
      // The session ended and cancelled it: that is the behaviour under test.
    }
  });
  await page.getByRole("link", { name: "Review" }).first().click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.waitForTimeout(2500);
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await expect(page.getByText(ITEM.first)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Review email" })).toHaveCount(0);
});

test("a second identity sees nothing of the first session", async ({ browser, baseURL }) => {
  expect(baseURL).toBeDefined();
  const first = await browser.newContext({ baseURL });
  const firstPage = await first.newPage();
  try {
    await signIn(firstPage);
    await firstPage.goto("/#/queue");
    await expect(firstPage.getByText(ITEM.first).first()).toBeVisible();
  } finally {
    await firstPage.close();
    await first.close();
  }

  const second = await browser.newContext({ baseURL });
  const page = await second.newPage();
  try {
    const statuses: Array<[number, string]> = [];
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.pathname.startsWith("/api")) statuses.push([response.status(), url.pathname]);
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Use owner key instead" }).click();
    await page.getByLabel("Owner key").fill("another-identity-not-registered-here");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText(ITEM.first)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Review email" })).toHaveCount(0);
    expect(statuses.some(([status, path]) => path === "/api/session" && status === 401)).toBe(true);
    expect((await page.context().cookies()).some((cookie) => cookie.name === "probation_owner_session")).toBe(false);

    // Same browser, now with the owner that the data actually belongs to.
    await page.getByLabel("Owner key").fill(OWNER_KEY);
    await page.getByRole("button", { name: "Continue" }).click();
    await page.goto("/#/queue");
    await expect(page.getByText(ITEM.first).first()).toBeVisible();
  } finally {
    await page.close();
    await second.close();
  }
});
