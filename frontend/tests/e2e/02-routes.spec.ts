import { expect, test } from "@playwright/test";
import { ITEM, OWNER_KEY, signIn } from "./e2e-support";

/** Route coverage for the frozen screen map, plus refresh / Back / forward honesty. */

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("every primary route renders its own screen", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: /needs? your decision/i }).first()).toBeVisible();

  await page.goto("/#/queue");
  await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();

  await page.goto("/#/queue/proposal");
  await expect(page.getByRole("heading", { name: ITEM.first })).toBeVisible();

  await page.goto("/#/watching");
  await expect(page.getByRole("heading", { name: "Watching" })).toBeVisible();
  await expect(page.getByText(ITEM.shadow)).toBeVisible();
  await expect(page.getByText("Nothing here is waiting for your decision")).toHaveCount(0);

  await page.goto("/#/watching/e2e-shadow-1");
  await expect(page.getByRole("heading", { name: ITEM.shadow })).toBeVisible();
  await expect(page.getByText("Nothing here is waiting for your decision. Probation is only observing.")).toBeVisible();

  await page.goto("/#/actions");
  await expect(page.getByRole("heading", { name: "Actions" })).toBeVisible();

  await page.goto("/#/permissions");
  await expect(page.getByRole("heading", { name: "Permissions" })).toBeVisible();

  await page.goto("/#/more");
  await expect(page.getByRole("heading", { name: "More" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "More destinations" })).toBeVisible();

  for (const section of ["insights", "metrics", "habits", "chains", "exams", "connections", "usage", "privacy", "activity", "settings", "help", "radar", "library"]) {
    await page.goto(`/#/more/${section}`);
    await expect(page.getByRole("main").getByRole("heading", { name: "More" })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "More destinations" }).getByRole("link", { name: sectionLabel(section) }),
    ).toHaveAttribute("aria-current", "page");
  }

  await page.goto("/#/requests/synthetic-request-that-does-not-exist");
  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();
  await expect(page.getByRole("alert").getByRole("heading", { name: "Status unavailable" })).toBeVisible();
});

function sectionLabel(section: string): string {
  const labels: Record<string, string> = {
    insights: "Performance",
    metrics: "Counts and trends",
    habits: "Learned about you",
    chains: "Follow-on patterns",
    exams: "Trick-question tests",
    connections: "Connections",
    usage: "Cost and usage",
    privacy: "Privacy and web",
    activity: "Activity record",
    settings: "Settings in use",
    help: "Help and limits",
    radar: "Radar",
    library: "Reading library",
  };
  return labels[section] ?? section;
}

test("an unknown route is a clear not-found state, never a blank screen", async ({ page }) => {
  await page.goto("/#/nowhere-to-be-found");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(page.getByText("This address is not part of Probation. Nothing was changed and nothing was sent.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to Home" })).toBeVisible();

  await page.goto("/#/more/not-a-section");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();

  await page.goto("/#/queue/proposal/extra/segment");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("a deep link survives a reload", async ({ page }) => {
  await page.goto("/#/queue/e2e-ask-2");
  await expect(page.getByRole("heading", { name: ITEM.conflict })).toBeVisible();
  await page.reload();
  // The owner key is memory-only by contract, so a refresh returns to the sign-in screen and
  // shows no private data. The deep-linked route must survive that, and come back after
  // re-authentication rather than being overwritten by Home.
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await expect(page).toHaveURL(/#\/queue\/e2e-ask-2/);
  await expect(page.getByRole("listitem")).toHaveCount(0);
  await page.getByLabel("Owner key").fill(OWNER_KEY);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: ITEM.conflict })).toBeVisible();

  await page.goto("/#/more/settings");
  await page.reload();
  // Same contract as the reload assertion above: the route survives, the session does not.
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toBeVisible();
  await expect(page).toHaveURL(/#\/more\/settings/);
  await page.getByLabel("Owner key").fill(OWNER_KEY);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByRole("navigation", { name: "More destinations" }).getByRole("link", { name: "Settings in use" }),
  ).toHaveAttribute("aria-current", "page");
});

test("Back returns to the filtered list and forward returns to the item", async ({ page }) => {
  await page.goto("/#/queue");
  await page.getByRole("button", { name: "Needs your decision" }).click();
  await expect(page).toHaveURL(/gate=ask/);
  await page.getByRole("listitem").filter({ hasText: ITEM.plain }).getByRole("button", { name: "Review email" }).click();
  await expect(page.getByRole("heading", { name: ITEM.plain })).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/#\/queue\?gate=ask/);
  const filter = page.getByRole("button", { name: "Needs your decision" });
  await expect(filter).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("listitem").filter({ hasText: ITEM.plain })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: ITEM.shadow })).toHaveCount(0);

  await page.goForward();
  await expect(page).toHaveURL(/#\/queue\/e2e-ask-3/);
  await expect(page.getByRole("heading", { name: ITEM.plain })).toBeVisible();
});

test("the in-app Back link returns to the list it came from", async ({ page }) => {
  await page.goto("/#/watching");
  await page.getByRole("link", { name: new RegExp(ITEM.shadow) }).click();
  await expect(page.getByRole("heading", { name: ITEM.shadow })).toBeVisible();
  await page.getByRole("link", { name: /Back to review/ }).click();
  await expect(page.getByRole("heading", { name: "Watching" })).toBeVisible();
});
