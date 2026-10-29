import { expect, test } from "@playwright/test";
import { ITEM, installGuards, signIn } from "./e2e-support";

/** Console cleanliness, same-origin-only traffic, and proof that the bundle is the built app. */

test("the golden read path logs no console errors and asks nothing off-origin", async ({ page, baseURL }) => {
  const guards = installGuards(page, baseURL);
  await signIn(page);
  await page.goto("/#/queue");
  await expect(page.getByText(ITEM.first).first()).toBeVisible();
  await page.goto("/#/queue/proposal");
  await expect(page.getByRole("heading", { name: "Why Probation suggested this" })).toBeVisible();
  await page.goto("/#/watching");
  await expect(page.getByText(ITEM.shadow)).toBeVisible();
  await page.goto("/#/actions");
  await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible();
  await page.goto("/#/permissions");
  await expect(page.getByRole("heading", { name: "Permissions" })).toBeVisible();
  await page.goto("/#/more/evidence");
  await expect(page.getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();
  await page.waitForTimeout(500);

  expect(guards.pageErrors, `page errors: ${guards.pageErrors.join("\n")}`).toEqual([]);
  expect(guards.consoleErrors, `console errors: ${guards.consoleErrors.join("\n")}`).toEqual([]);
  expect(guards.externalRequests, `non-loopback requests: ${guards.externalRequests.join("\n")}`).toEqual([]);
  const hardFailures = guards.failedRequests.filter((entry) => !entry.includes("ERR_ABORTED"));
  expect(hardFailures, `failed requests: ${hardFailures.join("\n")}`).toEqual([]);
  expect(guards.apiRequests.some((entry) => entry.includes("/api/queue"))).toBe(true);
});

test("the run serves the production bundle, not the dev server", async ({ page, baseURL }) => {
  const requested: string[] = [];
  page.on("request", (request) => requested.push(request.url()));
  await signIn(page);
  const origin = new URL(baseURL ?? "http://127.0.0.1").origin;
  const assets = requested.filter((url) => url.startsWith(`${origin}/assets/`));
  expect(assets.length, "no hashed production assets were requested").toBeGreaterThan(1);
  expect(requested.some((url) => url.includes("/src/main.tsx")), "the dev server served the page").toBe(false);
  expect(requested.some((url) => url.includes("vite/@plugins/react") || url.includes("@react-refresh"))).toBe(false);
  expect(assets.some((url) => /-[A-Za-z0-9_-]{6,}\.js$/.test(url)), `not a hashed bundle: ${assets.join(", ")}`).toBe(true);
});

test("fonts and icons come from the bundle, never a remote foundry", async ({ page, baseURL }) => {
  const requested: string[] = [];
  page.on("request", (request) => requested.push(request.url()));
  await signIn(page);
  const origin = new URL(baseURL ?? "http://127.0.0.1").origin;
  const offOrigin = requested.filter((url) => !url.startsWith(origin) && !url.startsWith("data:") && !url.startsWith("blob:"));
  expect(offOrigin, `off-origin fetches: ${offOrigin.join(", ")}`).toEqual([]);
  expect(requested.some((url) => /fonts\.(googleapis|gstatic)\.com/.test(url))).toBe(false);
});
