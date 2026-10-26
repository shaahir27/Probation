import { expect, test } from "@playwright/test";

const syntheticOwnerKey = "d6-e2e-synthetic-owner-key-only-never-for-private-use";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.getByLabel("Owner key").fill(syntheticOwnerKey);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "1 email needs your decision" })).toBeVisible();
}

test("home stays readable at desktop, tablet, and phone widths", async ({ page }, testInfo) => {
  await signIn(page);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("heading", { name: "1 email needs your decision" })).toBeVisible();
    const viewportIsNotWiderThanContent = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(viewportIsNotWiderThanContent, `horizontal overflow at ${width}px`).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`taste-${width}.png`), fullPage: true });
  }
  await page.getByRole("link", { name: /Queue/ }).click();
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByText("Some information.")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`queue-${width}.png`), fullPage: true });
  }
});

test("sign-in keeps the key in memory and shows the synthetic review item", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.getByLabel("Owner key").fill("incorrect-synthetic-key");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toBeVisible();

  await page.getByLabel("Owner key").fill(syntheticOwnerKey);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "1 email needs your decision" })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(page.getByText("1 waiting")).toBeVisible();
  await expect(page.getByText("Some information.")).toBeVisible();
  await page.getByRole("button", { name: "Review email" }).click();
  await expect(page.getByRole("heading", { name: "Some information." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Why Probation suggested this" })).toBeVisible();
});

test("sign-out returns to the masked key form", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await expect(page.getByLabel("Owner key")).toHaveValue("");
});

test("leaving an email shows request status without claiming completion", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Queue" }).click();
  await page.getByRole("button", { name: "Review email" }).click();
  await page.getByRole("button", { name: "Leave as is" }).click();

  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();
  await expect(page.getByText("Your request was received. Probation is still processing it.")).toBeVisible();
  await expect(page.getByText("Probation confirmed this action.")).toHaveCount(0);
});
