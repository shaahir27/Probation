import { expect, type Locator, type Page } from "@playwright/test";

/** The synthetic owner key for this harness only. Never a real credential. */
export const OWNER_KEY = "d6-e2e-synthetic-owner-key-only-never-for-private-use";

/** Summaries are the seeded synthetic text; specs address rows by them, never by index. */
export const ITEM = {
  first: "Notice of renewal — payment due 5 November",
  conflict: "Your renewal window closed on 30 September",
  plain: "Committee vote on the autumn schedule",
  shadow: "Newsletter 42 — what changed this month",
  cited: "Renewal notice — payment due 5 November",
} as const;

export interface Guards {
  consoleErrors: string[];
  pageErrors: string[];
  externalRequests: string[];
  failedRequests: string[];
  apiRequests: string[];
}

/** Everything the run must prove about the browser surface: no errors, no third-party traffic. */
export function installGuards(page: Page, baseURL: string | undefined): Guards {
  if (!baseURL) throw new Error("This project has no loopback baseURL");
  const origin = new URL(baseURL).origin;
  const guards: Guards = { consoleErrors: [], pageErrors: [], externalRequests: [], failedRequests: [], apiRequests: [] };
  page.on("console", (message) => {
    if (message.type() === "error") guards.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => guards.pageErrors.push(String(error)));
  page.on("requestfailed", (request) =>
    guards.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`),
  );
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api")) guards.apiRequests.push(`${request.method()} ${url.pathname}`);
    const loopback = url.protocol === "http:" && /^(127\.0\.0\.1|localhost)(:\d+)?$/.test(url.host);
    const same = url.origin === origin;
    if (url.protocol !== "data:" && url.protocol !== "about:" && !(loopback && same)) {
      guards.externalRequests.push(`${request.method()} ${request.url()}`);
    }
  });
  return guards;
}

export async function signIn(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await page.getByRole("button", { name: "Use owner key instead" }).click();
  await page.getByLabel("Owner key").fill(OWNER_KEY);
  await page.getByRole("button", { name: "Continue" }).click();
  // The app's own post-sign-in navigation lands on Home. Wait for it, otherwise a
  // goto() issued immediately after would be overwritten by it mid-flight.
  await expect(page).toHaveURL(/#\/home/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
}

/** Opens one seeded item's detail directly, so no test depends on row order. */
export async function openItem(page: Page, summary: string): Promise<void> {
  await page.goto("/#/queue");
  const row = page.getByRole("listitem").filter({ hasText: summary });
  await expect(row.getByRole("button", { name: "Review email" })).toBeVisible();
  await row.getByRole("button", { name: "Review email" }).click();
  await expect(page.getByRole("heading", { name: summary })).toBeVisible();
}

export async function hasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth > 1);
}

/**
 * Measures a control instead of reading its CSS: the box must be inside the viewport and
 * its own centre point must resolve back to it (nothing painted over it).
 */
export async function expectReachable(page: Page, locator: Locator): Promise<void> {
  const box = await locator.boundingBox();
  expect(box, "the control has a measured box").not.toBeNull();
  if (box === null) return;
  expect(box.width, "the primary touch target is at least 44px wide").toBeGreaterThanOrEqual(44);
  expect(box.height, "the primary touch target is at least 44px tall").toBeGreaterThanOrEqual(44);
  const viewport = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
  expect(box.x, "left edge").toBeGreaterThanOrEqual(-0.5);
  expect(box.y, "top edge").toBeGreaterThanOrEqual(-0.5);
  expect(box.x + box.width, "right edge").toBeLessThanOrEqual(viewport.width + 0.5);
  expect(box.y + box.height, "bottom edge").toBeLessThanOrEqual(viewport.height + 0.5);
  const reached = await locator.evaluate(
    (node, point) => {
      const hit = document.elementFromPoint(point.x, point.y);
      if (hit === null) return "none";
      if (hit === node || node.contains(hit) || hit.contains(node)) return "same";
      return `covered-by-${hit.tagName.toLowerCase()}`;
    },
    { x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2) },
  );
  expect(reached, "the primary action is not obscured").toBe("same");
}

/** The screen's one primary action: ink-on-canvas fill, as frozen by the design brief. */
export function primaryAction(page: Page): Locator {
  return page.locator('main button[class*="bg-ink"], main a[class*="bg-ink"]').first();
}

export const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';
