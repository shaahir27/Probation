import { expect, test } from "@playwright/test";
import { ITEM, signIn } from "./e2e-support";

/** Email-demo routes and useful setup destinations, plus refresh / Back / forward honesty. */

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("the demo navigation focuses on email review and its real outcomes", async ({ page }) => {
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  for (const [route, label] of [["home", "Overview"], ["queue", "Review"], ["actions", "Activity"], ["permissions", "Permissions"]]) {
    await expect(navigation.locator(`a[href="#/${route}"]`)).toContainText(label);
  }
  await expect(navigation.getByRole("link", { name: /Radar|Reading library|Habits|Chains|Calendar|Files/ })).toHaveCount(0);
  await page.goto("/#/more");
  const settings = page.getByRole("navigation", { name: "More destinations" });
  await expect(settings.getByRole("link")).toHaveCount(3);
  for (const label of ["Evidence", "Access & privacy", "Record & rules"]) {
    await expect(settings.getByRole("link", { name: label })).toBeVisible();
  }
  await expect(settings.getByRole("link", { name: /Radar|Reading library|Follow-on patterns/ })).toHaveCount(0);
});

test("every primary route renders its own screen", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Workspace overview" })).toBeVisible();

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
  await page.getByRole("link", { name: "Choose an action yourself" }).click();
  await expect(page).toHaveURL(/#\/queue\/e2e-shadow-1/);
  await expect(page.getByRole("heading", { name: "Your decision" })).toBeVisible();

  await page.goto("/#/actions");
  await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible();

  await page.goto("/#/permissions");
  await expect(page.getByRole("heading", { name: "Permissions" })).toBeVisible();

  await page.goto("/#/more");
  await expect(page.getByRole("heading", { name: "More", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "More destinations" })).toBeVisible();

  for (const [section, label] of [["evidence", "Evidence"], ["access", "Access & privacy"], ["record", "Record & rules"]] as const) {
    await page.goto(`/#/more/${section}`);
    await expect(page.getByRole("main").getByRole("heading", { name: label, exact: true })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "More destinations" }).getByRole("link", { name: label }),
    ).toHaveAttribute("aria-current", "page");
  }
  // Old URLs remain aliases into the three pages.
  await page.goto("/#/more/insights");
  await expect(page.getByRole("main").getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "More destinations" }).getByRole("link", { name: "Evidence" }),
  ).toHaveAttribute("aria-current", "page");

  await page.goto("/#/requests/synthetic-request-that-does-not-exist");
  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();
  await expect(page.getByRole("alert").getByRole("heading", { name: "Status unavailable" })).toBeVisible();
});


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

test("a deep link survives a reload inside the owner session", async ({ page }) => {
  await page.goto("/#/queue/e2e-ask-2");
  await expect(page.getByRole("heading", { name: ITEM.conflict })).toBeVisible();
  await page.reload();
  // The HttpOnly session cookie survives a refresh and the key was never stored, so the
  // deep-linked item comes back directly instead of a sign-in screen.
  await expect(page.getByRole("heading", { name: ITEM.conflict })).toBeVisible();
  await expect(page).toHaveURL(/#\/queue\/e2e-ask-2/);
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toHaveCount(0);

  await page.goto("/#/more/record");
  await page.reload();
  await expect(
    page.getByRole("navigation", { name: "More destinations" }).getByRole("link", { name: "Record & rules" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "Sign in to your account" })).toHaveCount(0);
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
  await page.getByRole("link", { name: /Back to watching/ }).click();
  await expect(page.getByRole("heading", { name: "Watching" })).toBeVisible();
});

test("More reports failed reads and describes separate Gmail action access", async ({ page }) => {
  await page.route("**/api/metrics/summary", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "unavailable" }) }));
  await page.goto("/#/more/metrics");
  await expect(page.getByRole("heading", { name: "Counts are unavailable" })).toBeVisible();
  await expect(page.getByText("No weeks recorded yet.")).toHaveCount(0);
  await page.goto("/#/more/help");
  await expect(page.getByText("Gmail read access and action access require separate consent.", { exact: false })).toBeVisible();
  await expect(page.getByText("This build does not send, archive or trash mail.", { exact: false })).toHaveCount(0);
});
