import { expect, test } from "@playwright/test";
import { installGuards, signIn } from "./e2e-support";

test("Connect apps shows real read-only Gmail status and clearly planned integrations", async ({ page, baseURL }, testInfo) => {
  const guards = installGuards(page, baseURL);
  await signIn(page);
  const setupRead = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/gmail/setup/read" && response.request().method() === "GET");
  await page.getByRole("link", { name: "Connect apps", exact: true }).click();
  const response = await setupRead;
  expect(response.status()).toBe(200);
  const setup = await response.json() as { connected: boolean; status: string };
  expect(["connected", "not_connected"]).toContain(setup.status);

  const panel = page.getByRole("region", { name: "Connect apps" });
  const gmail = panel.getByRole("article").filter({ has: page.getByRole("heading", { name: "Gmail", exact: true }) });
  if (setup.connected) {
    await expect(gmail.getByRole("status")).toHaveText(/Connected.*read-only/);
    await expect(gmail.getByText("Read access", { exact: true })).toBeVisible();
    await expect(gmail.getByText("Action access", { exact: true })).toBeVisible();
    await expect(gmail.getByRole("button", { name: "Pause access" })).toBeVisible();
    await expect(gmail.getByRole("button", { name: "Disconnect Gmail" })).toBeVisible();

    // The destructive control confirms first and must not send anything until confirmed.
    await gmail.getByRole("button", { name: "Disconnect Gmail" }).click();
    await expect(gmail.getByText("Disconnect Gmail?")).toBeVisible();
    await gmail.getByRole("button", { name: "Keep connected" }).click();
    await expect(gmail.getByRole("button", { name: "Disconnect Gmail" })).toBeVisible();
  } else {
    await expect(gmail.getByRole("button", { name: "Connect Gmail" })).toBeEnabled();
  }

  for (const [name, icon] of [["Gmail", "gmail"], ["Google Calendar", "calendar"], ["Google Drive", "drive"]] as const) {
    const app = panel.getByRole("article").filter({ has: page.getByRole("heading", { name, exact: true }) });
    const image = app.locator("img");
    await expect(image).toHaveAttribute("src", `/integrations/${icon}.webp`);
    await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
    if (icon !== "gmail") {
      await expect(app.getByText("Planned", { exact: true })).toBeVisible();
      await expect(app.getByRole("button")).toHaveCount(0);
    }
  }
  expect(guards.apiRequests.filter((request) => request.startsWith("POST /api/gmail/setup/"))).toEqual([]);
  expect(await panel.innerText()).not.toContain("\uFFFD");
  expect(guards.externalRequests).toEqual([]);
  expect(guards.pageErrors).toEqual([]);
  expect(guards.consoleErrors).toEqual([]);

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({ path: testInfo.outputPath(`connect-apps-${width}.png`), fullPage: true });
  }
});
