import { expect, test } from "@playwright/test";
import { ITEM, expectReachable, hasHorizontalOverflow, primaryAction, signIn } from "./e2e-support";

/** 360 / 390 / 768 / 1440 with no horizontal overflow and no obscured primary action. */

const WIDTHS = [360, 390, 768, 1440] as const;

test("the primary screens fit and their main action stays reachable at every width", async ({ page }) => {
  await signIn(page);
  const screens: Array<[string, string | null]> = [
    ["/#/", "Workspace overview"],
    ["/#/queue", ITEM.first],
    ["/#/queue/proposal", "Why Probation suggested this"],
  ];
  for (const [route, marker] of screens) {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(route);
      await expect(page.getByRole("main")).toBeVisible();
      if (marker !== null) await expect(page.getByText(marker).first()).toBeVisible();
      expect(await hasHorizontalOverflow(page), `horizontal overflow on ${route} at ${width}px`).toBe(false);
      const action = primaryAction(page);
      await expect(action, `a primary action exists on ${route}`).toHaveCount(1);
      await action.scrollIntoViewIfNeeded();
      await expectReachable(page, action);
    }
  }
});

test("the mobile bar never covers the action it sits under", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 700 });
  await signIn(page);
  await page.goto("/#/queue");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav).toBeVisible();
  const box = await nav.boundingBox();
  expect(box).not.toBeNull();
  const action = primaryAction(page);
  await action.scrollIntoViewIfNeeded();
  await expectReachable(page, action);
  const actionBox = await action.boundingBox();
  expect(actionBox!.y + actionBox!.height).toBeLessThanOrEqual(box!.y + 1);
});

test("secondary screens do not overflow either", async ({ page }) => {
  await signIn(page);
  for (const route of ["/#/watching", "/#/actions", "/#/permissions", "/#/more", "/#/more/evidence", "/#/more/access", "/#/more/record"]) {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(route);
      await expect(page.getByRole("main")).toBeVisible();
      expect(await hasHorizontalOverflow(page), `horizontal overflow on ${route} at ${width}px`).toBe(false);
    }
  }
});

test("200 percent zoom keeps content unclipped", async ({ page }) => {
  await signIn(page);
  // Two ways to ask the same question: a halved CSS viewport, and real CSS zoom.
  await page.setViewportSize({ width: 720, height: 640 });
  await page.goto("/#/queue");
  await expect(page.getByText(ITEM.first).first()).toBeVisible();
  expect(await hasHorizontalOverflow(page)).toBe(false);

  await page.goto("/#/queue/proposal");
  await expect(page.getByRole("heading", { name: ITEM.first })).toBeVisible();
  expect(await hasHorizontalOverflow(page)).toBe(false);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/#/queue");
  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  await expect(page.getByText(ITEM.first).first()).toBeVisible();
  expect(await hasHorizontalOverflow(page), "content clipped at 200% zoom").toBe(false);
  const clipped = await page.evaluate(() =>
    Array.from(document.querySelectorAll("main h1, main h2, main p")).some((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.width === 0) return false;
      return rect.right > document.documentElement.clientWidth + 2;
    }),
  );
  expect(clipped, "a heading or paragraph runs past the viewport at 200% zoom").toBe(false);
});

test("opening a review uses the workspace without an empty list column", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await page.goto("/#/queue/proposal");
  await expect(page.locator(".review-list-pane")).toBeHidden();
  await expect(page.getByRole("link", { name: "Back to review" })).toBeVisible();
  await page.getByRole("link", { name: "Back to review" }).click();
  await expect(page.locator(".review-list-pane")).toBeVisible();
});
