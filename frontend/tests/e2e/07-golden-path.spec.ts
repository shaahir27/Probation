import { expect, test, type Page } from "@playwright/test";
import { ITEM, installGuards, openItem, signIn } from "./e2e-support";

/**
 * The durable-mutation journey against the real API and the built bundle:
 * review -> bound payload -> HTTP 202 -> poll -> truthful decision/execution split,
 * plus the 409 conflict path and server-derived undo.
 */

interface ReviewCall {
  hash: string;
  body: Record<string, unknown>;
  status: number;
}

async function captureReview(page: Page, button: RegExp): Promise<ReviewCall> {
  const reviewResponse = page.waitForResponse(
    (response) => /\/api\/queue\/[^/]+\/review$/.test(response.url()) && response.request().method() === "POST",
  );
  const respondResponse = page.waitForResponse(
    (response) => /\/api\/queue\/[^/]+\/respond$/.test(response.url()) && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: button }).click();
  const review = await reviewResponse;
  const reviewJson = (await review.json()) as { reviewed_payload_hash: string; reviewed_payload?: Record<string, unknown> };
  const respond = await respondResponse;
  const respondBody = JSON.parse(String(respond.request().postData())) as Record<string, unknown>;
  return { hash: reviewJson.reviewed_payload_hash, body: respondBody, status: respond.status() };
}

test("reviewing an item records a durable request and never claims it finished", async ({ page, baseURL }) => {
  const guards = installGuards(page, baseURL);
  await signIn(page);
  await page.goto("/#/queue");
  await expect(page.getByText(ITEM.first).first()).toBeVisible();
  await openItem(page, ITEM.first);

  // The recommendation, the reason and the only decisions the server supports.
  await expect(page.getByRole("heading", { name: "Why Probation suggested this" })).toBeVisible();
  await expect(page.getByText("You archived a very similar notice from this sender last time.")).toBeVisible();
  await page.getByText("Choose another action", { exact: true }).click();
  await expect(page.getByLabel("Action to take")).toContainText("Archive email");

  const call = await captureReview(page, /^Archive email$/);
  expect(call.status, "the mutation did not return HTTP 202").toBe(202);
  expect(call.body.reviewed_payload_hash, "the submitted payload is not the reviewed binding").toBe(call.hash);
  expect(String(call.body.request_id)).toMatch(/^review-/);
  expect(String(call.body.version)).toBe("v2");
  expect(String(call.body.response)).toBe("accept");

  await expect(page).toHaveURL(/#\/requests\/review-/);
  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();
  await expect(page.getByText("Your request was received. Probation is still processing it.")).toBeVisible();
  await expect(page.getByText("Probation confirmed this action.")).toHaveCount(0);
  await expect(page.getByText(/decision: .* · execution:/)).toBeVisible();

  // The page polls the durable request on its own; the status URL is the only truth.
  await expect
    .poll(async () => guards.apiRequests.filter((entry) => entry.startsWith("GET /api/responses/")).length, { timeout: 20_000 })
    .toBeGreaterThanOrEqual(2);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();

  await page.goto("/#/queue");
  await expect(page.getByText(ITEM.first)).toHaveCount(0);
  await page.goto("/#/queue/proposal");
  await expect(page.getByText("You already answered this: accept.")).toBeVisible();
  expect(guards.externalRequests, guards.externalRequests.join("\n")).toEqual([]);
  expect(guards.pageErrors, guards.pageErrors.join("\n")).toEqual([]);
});

test("a changed payload after a decision conflicts and demands a fresh review", async ({ page, browser, baseURL }) => {
  const guards = installGuards(page, baseURL);
  await signIn(page);
  await openItem(page, ITEM.conflict);
  await expect(page.getByRole("button", { name: "Reject suggestion" })).toBeVisible();

  // A separate session of the same owner answers the email first. First valid decision wins.
  const otherContext = await browser.newContext({ baseURL });
  const other = await otherContext.newPage();
  try {
    await signIn(other);
    await other.goto("/#/queue/e2e-ask-2");
    await expect(other.getByRole("heading", { name: ITEM.conflict })).toBeVisible();
    const firstCall = await captureReview(other, /^Reject suggestion$/);
    expect(firstCall.status).toBe(202);

    // The stale screen still offers a decision; sending it must conflict, not resend.
    const conflictResponse = page.waitForResponse((response) => /\/api\/queue\/[^/]+\/respond$/.test(response.url()));
    await page.getByRole("button", { name: "Archive email" }).click();
    const conflicted = await conflictResponse;
    expect(conflicted.status(), "the server did not report a conflict").toBe(409);

    const alert = page.getByRole("alert");
    await expect(alert.getByText("Nothing was sent.", { exact: true })).toBeVisible();
    await expect(alert.getByText(/already been answered|no longer current/)).toBeVisible();
    await expect(alert.getByRole("button", { name: "Review it again" })).toBeVisible();

    // Fresh review, not a resend: the dropped binding forces a new /review before anything else.
    await alert.getByRole("button", { name: "Review it again" }).click();
    await expect(page.getByText("Your decision is already recorded")).toBeVisible();
    await expect(page.getByRole("button", { name: /Archive email|Reject suggestion|Leave as is/ })).toHaveCount(0);
    const responds = guards.apiRequests.filter((entry) => entry.endsWith("/respond"));
    expect(responds.length, `the UI resent a decision after the conflict: ${responds.join(", ")}`).toBe(1);
  } finally {
    await other.close();
    await otherContext.close();
  }
});

test("undo appears only where the server offers it and a cancel stays queued", async ({ page, baseURL }) => {
  await signIn(page);
  await page.goto("/#/actions");
  const held = page.getByRole("listitem").filter({ hasText: ITEM.conflict }).first();
  await expect(held.getByText("Waiting before action")).toBeVisible();
  await expect(held.getByRole("button", { name: "Cancel action" })).toBeVisible();

  const expired = page.getByRole("listitem").filter({ hasText: ITEM.first }).first();
  await expect(expired.getByRole("button", { name: /Cancel action|Undo action/ })).toHaveCount(0);
  await expect(expired.getByText("Undo is not available for this action.")).toBeVisible();

  const undoResponse = page.waitForResponse((response) => /\/api\/actions\/[^/]+\/undo$/.test(response.url()));
  await held.getByRole("button", { name: "Cancel action" }).click();
  const receipt = await undoResponse;
  expect(receipt.status(), "the cancel intent was not accepted").toBe(202);
  const body = (await receipt.json()) as { status: string; status_url: string };
  expect(body.status).toBe("recorded");
  expect(body.status_url).toContain("/api/responses/");

  await expect(page).toHaveURL(/#\/requests\/undo-/);
  await expect(page.getByText("Your request was received. Probation is still processing it.")).toBeVisible();
  await expect(page.getByText("The action was cancelled.")).toHaveCount(0);
  void baseURL;
});
