import { expect, test } from "@playwright/test";

const syntheticOwnerKey = "d6-e2e-synthetic-owner-key-only-never-for-private-use";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.getByRole("button", { name: "Use owner key instead" }).click();
  await page.getByLabel("Owner key").fill(syntheticOwnerKey);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();
  await expect(page.getByText("1 waiting", { exact: true })).toBeVisible();
}

test("home stays readable at desktop, tablet, and phone widths", async ({ page }, testInfo) => {
  await signIn(page);
  for (const width of [1440, 768, 390, 360]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();
    const viewportIsNotWiderThanContent = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(viewportIsNotWiderThanContent, `horizontal overflow at ${width}px`).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`taste-${width}.png`), fullPage: true });
  }
  await page.getByRole("link", { name: /^Review emails/ }).click();
  for (const width of [1440, 768, 390, 360]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByText("Notice of renewal — payment due 5 November")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`queue-${width}.png`), fullPage: true });
  }
});

test("sign-in stores no key in browser storage and shows the synthetic review item", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.getByRole("button", { name: "Use owner key instead" }).click();
  await page.getByLabel("Owner key").fill("incorrect-synthetic-key");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toBeVisible();

  await page.getByLabel("Owner key").fill(syntheticOwnerKey);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();
  await expect(page.getByText("1 waiting", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);

  await page.getByRole("link", { name: /^Review emails/ }).click();
  await expect(page.getByText("1 waiting", { exact: true })).toBeVisible();
  await expect(page.getByText("Notice of renewal — payment due 5 November")).toBeVisible();
  await page.getByRole("button", { name: "Review email" }).click();
  await expect(page.getByRole("heading", { name: "Notice of renewal — payment due 5 November" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Why Probation suggested this" })).toBeVisible();
});

test("account sign-up and sign-in persist through refresh without browser credentials", async ({ page }) => {
  const email = "local-owner@example.test";
  const password = "local-test-password-2026";
  await page.goto("/");
  await page.getByRole("button", { name: "Create an account" }).click();
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);

  await page.reload();
  await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();
});

test("sign-out returns to the account form with no password retained", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveValue("");
  await expect(page.getByLabel("Password")).toHaveValue("");
});

test("leaving an email shows request status without claiming completion", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: /^Review emails/ }).click();
  await page.getByRole("button", { name: "Review email" }).click();
  await page.getByRole("button", { name: "Leave as is" }).click();

  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();
  await expect(page.getByText("Your request was received. Probation is still processing it.")).toBeVisible();
  await expect(page.getByText("Probation confirmed this action.")).toHaveCount(0);
});
