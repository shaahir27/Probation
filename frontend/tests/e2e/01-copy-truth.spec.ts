import { expect, test } from "@playwright/test";
import { ITEM, openItem, signIn } from "./e2e-support";

/**
 * D6 copy and truthfulness contract (docs/wp9/D6_COPY_DECK.md, section 12.2).
 * Every assertion here reads what the real API put on screen.
 */

test("the queue speaks in plain words, never in gate tokens", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/queue");
  await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Needs your decision" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Suggested for you" })).toBeVisible();
  const main = page.getByRole("main");
  for (const token of ["ASK", "SUGGEST", "SHADOW", "EXECUTE_UNDO", "HOLD_THEN_EXECUTE"]) {
    await expect(main.getByText(token, { exact: true })).toHaveCount(0);
  }
  await expect(main.getByText("Needs your decision").first()).toBeVisible();
});

test("evidence maths, class keys and technical detail sit behind Details", async ({ page }) => {
  await signIn(page);
  await openItem(page, ITEM.plain);
  const main = page.getByRole("main");
  await expect(main.getByText("Why Probation suggested this")).toBeVisible();
  // The task key and the evidence maths live inside a collapsed <details>, so they are in the
  // document but not shown: "behind Details" means not visible until the owner opens it.
  await expect(main.getByText(/mail\|fyi\|frequent/)).not.toBeVisible();
  await expect(main.getByText(/matching choices out of/)).not.toBeVisible();
  await main.getByText("Details", { exact: true }).click();
  await expect(main.getByText(/Task: mail\|fyi\|frequent/)).toBeVisible();
  await expect(main.getByText(/matching choices out of/)).toBeVisible();
});

test("the web check card distinguishes checked, partial, not checked and unavailable", async ({ page }) => {
  await signIn(page);

  await openItem(page, ITEM.first);
  await expect(page.getByRole("heading", { name: "Web check" })).toBeVisible();
  await expect(page.getByText("Unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("This information is unavailable right now.")).toBeVisible();

  await openItem(page, ITEM.conflict);
  await expect(page.getByText("Partial", { exact: true })).toBeVisible();
  await expect(page.getByText("Probation read some of what it expected")).toBeVisible();

  await openItem(page, ITEM.plain);
  await expect(page.getByText("Not checked", { exact: true })).toBeVisible();
  await expect(page.getByText("Probation did not check the web for this email.")).toBeVisible();

  await openItem(page, ITEM.cited);
  await expect(page.getByText("Checked", { exact: true })).toBeVisible();
  await expect(page.getByText("Cited as free", { exact: true })).toBeVisible();
});

test("citations render as safe links and an unknown fee is never shown as free", async ({ page }) => {
  await signIn(page);
  await openItem(page, ITEM.conflict);
  const card = page.getByRole("region", { name: "Web check" });
  await expect(card.getByText("Cost not confirmed", { exact: true })).toBeVisible();
  await expect(card.getByText(/Probation has not confirmed whether anything costs money/)).toBeVisible();
  await expect(card.getByText(/free/i)).toHaveCount(0);
  const source = card.getByRole("listitem").locator("a").first();
  await expect(source).toHaveAttribute("href", /^https:/);
  await expect(source).toHaveAttribute("rel", /noopener/);
  await expect(source).toHaveAttribute("rel", /noreferrer/);
});

test("an unconfirmed effect reads Result not confirmed, never Completed", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/actions");
  const reconciliation = page.getByRole("listitem").filter({ hasText: ITEM.cited }).first();
  await expect(reconciliation.getByText("Result not confirmed")).toBeVisible();
  await expect(
    reconciliation.getByText("Probation could not confirm whether this happened. Check the email before trying again."),
  ).toBeVisible();
  await expect(reconciliation.getByText("Completed")).toHaveCount(0);
});

test("undo is offered only where the server says it is available", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/actions");
  const held = page.getByRole("listitem").filter({ hasText: ITEM.conflict }).first();
  await expect(held.getByRole("button", { name: "Cancel action" })).toBeVisible();
  const expired = page.getByRole("listitem").filter({ hasText: ITEM.plain }).first();
  await expect(expired.getByRole("button", { name: /Undo action|Cancel action/ })).toHaveCount(0);
  await expect(expired.getByText("Undo is not available for this action.")).toBeVisible();
  await expect(expired.getByText(/Undo window until/)).toBeVisible();
});

test("licence levels read as plain words and permission stays read-only", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/permissions");
  const main = page.getByRole("main");
  await expect(main.getByText("These are read-only").first()).toBeVisible();
  await expect(main.getByText(/^(Watching|Suggests|Acts with undo|Acts automatically|No permissions yet)/).first()).toBeVisible();
  await expect(main.getByText(/\bL[0-3]\b/)).toHaveCount(0);
  await expect(main.getByRole("textbox")).toHaveCount(0);
});

test("a destination that is not accepted says so and shows no invented rows", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/more/library");
  await expect(page.getByText("Reading library is unavailable")).toBeVisible();
  await expect(page.getByRole("main").getByRole("listitem")).toHaveCount(0);

  await page.goto("/#/more/radar");
  // Either genuinely unavailable, or active-but-empty and stated as not accepted for release.
  // What must never happen is a board that looks like a finished feature.
  await expect(page.getByText(/Radar is unavailable|not accepted for release/)).toBeVisible();
  const radarList = page.getByRole("main").getByRole("list");
  await expect(radarList).toHaveCount(0);
});

test("an unanswered item never claims an action happened", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/queue");
  await expect(page.getByText("Probation has not acted on any of them")).toBeVisible();
  await expect(page.getByText("Probation confirmed this action.")).toHaveCount(0);
});
