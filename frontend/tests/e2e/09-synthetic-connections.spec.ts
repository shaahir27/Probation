import { expect, test } from "@playwright/test";
import { installGuards } from "./e2e-support";

test("the server-selected synthetic workspace cannot connect a real account", async ({ page, baseURL }) => {
  const guards = installGuards(page, baseURL);
  await page.goto("/#/more/connections");
  const panel = page.getByRole("region", { name: "Connect apps" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Real accounts are connected only in the private app.", { exact: false })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Connect Gmail" })).toBeDisabled();
  for (const name of ["Google Calendar", "Google Drive"]) {
    const app = panel.getByRole("article").filter({ has: page.getByRole("heading", { name, exact: true }) });
    await expect(app.getByText("Planned", { exact: true })).toBeVisible();
    await expect(app.getByRole("button")).toHaveCount(0);
  }
  expect(guards.apiRequests.filter((request) => request.includes("/api/gmail/setup/"))).toEqual([]);
  expect(await panel.innerText()).not.toContain("\uFFFD");
  expect(guards.externalRequests).toEqual([]);
  expect(guards.pageErrors).toEqual([]);
  expect(guards.consoleErrors).toEqual([]);
});
