import { expect, test, type Page } from "@playwright/test";
import { FOCUSABLE, ITEM, OWNER_KEY, signIn } from "./e2e-support";

/** Keyboard-only operation, announced errors, real names, reduced motion. */

async function focusTrail(page: Page, steps: number): Promise<string[]> {
  const seen: string[] = [];
  await page.locator("body").focus();
  for (let index = 0; index < steps; index += 1) {
    await page.keyboard.press("Tab");
    const identity = await page.evaluate(() => {
      const node = document.activeElement as HTMLElement | null;
      if (node === null) return "";
      const labelledBy = node.getAttribute("aria-labelledby");
      const fromLabel = labelledBy ? document.getElementById(labelledBy)?.textContent ?? "" : "";
      const forLabel = node.id ? document.querySelector(`label[for="${CSS.escape(node.id)}"]`)?.textContent ?? "" : "";
      const style = getComputedStyle(node);
      const focus =
        style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0
          ? "outline"
          : style.boxShadow !== "none"
            ? "ring"
            : "none";
      return [
        node.tagName.toLowerCase(),
        (node.getAttribute("aria-label") ?? node.textContent ?? forLabel ?? "").trim().slice(0, 40),
        focus,
      ].join("|");
    });
    if (identity !== "") seen.push(identity);
  }
  return seen;
}

test("tab order reaches every primary control and focus is visible", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/queue");
  const trail = await focusTrail(page, 26);
  const names = trail.map((entry) => entry.split("|")[1] ?? "");
  const joined = names.join(" ~ ");

  for (const required of ["Review", "Needs your decision", "Review email", "Actions", "More"]) {
    expect(joined, `tab order never reached "${required}"`).toContain(required);
  }
  const focusables = trail.filter((entry) => entry.startsWith("a|") || entry.startsWith("button|"));
  expect(focusables.length).toBeGreaterThan(4);
  // Every stop must show a real focus indicator (outline or Tailwind ring): a keyboard
  // stop with nothing drawn is a failure, not a style preference.
  for (const entry of focusables) {
    const [tag, name, focus] = entry.split("|");
    expect(focus, `no visible focus on ${tag} "${name}"`).toMatch(/outline|ring/);
  }
});

test("a review can be completed with the keyboard alone", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/queue");
  const row = page.getByRole("listitem").filter({ hasText: ITEM.conflict });
  await expect(row).toBeVisible();
  // No mouse: focus the row's control and press Enter.
  await row.getByRole("button", { name: "Review email" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: ITEM.conflict })).toBeVisible();

  const reject = page.getByRole("button", { name: "Reject suggestion" });
  await reject.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/requests\//);
  await expect(page.getByRole("heading", { name: "Request status" })).toBeVisible();
  // Decision and execution are two separate truths, and neither may read as done.
  await expect(page.getByText("Your request was received. Probation is still processing it.")).toBeVisible();
  await expect(page.getByText(/still recording your decision|Your decision was recorded/)).toBeVisible();
  await expect(page.getByText("No action was needed for this decision.")).toBeVisible();
  await expect(page.getByText("Probation confirmed this action.")).toHaveCount(0);
});

test("primary controls and landmarks have accessible names", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page);
  await page.goto("/#/queue/proposal");
  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("complementary")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);

  const unnamed = await page.evaluate((selector: string) => {
    const skipped = new Set(["SCRIPT", "STYLE"]);
    return Array.from(document.querySelectorAll<HTMLElement>(`main ${selector}`))
      .filter((node) => !skipped.has(node.tagName) && !node.closest('[hidden]'))
      .map((node) => {
        const labelledBy = node.getAttribute("aria-labelledby");
        const fromLabel = labelledBy ? (document.getElementById(labelledBy)?.textContent ?? "").trim() : "";
        const forLabel = node.id ? (document.querySelector(`label[for="${CSS.escape(node.id)}"]`)?.textContent ?? "").trim() : "";
        const name = (node.getAttribute("aria-label") ?? "").trim() || fromLabel || forLabel || node.textContent!.trim();
        return name === "" ? `${node.tagName.toLowerCase()}:${node.className}` : "";
      })
      .filter((entry) => entry !== "");
  }, FOCUSABLE);
  expect(unnamed, `controls with no accessible name: ${unnamed.join(", ")}`).toEqual([]);
});

test("errors are announced to assistive technology", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Owner key").fill("definitely-not-the-synthetic-key");
  await page.getByRole("button", { name: "Continue" }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  const message = (await alert.textContent())?.trim() ?? "";
  expect(message.length).toBeGreaterThan(10);
  const snapshot = await page.locator("main, form").first().ariaSnapshot();
  expect(snapshot).toContain("alert");
  expect(snapshot).toContain(message.slice(0, 20));
  // The failed field must also carry its error state, not just a colour.
  await expect(page.getByLabel("Owner key")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("Owner key")).toHaveAttribute("aria-describedby", "sign-in-error");

  // A real read announces through a polite live region too.
  await page.getByLabel("Owner key").fill(OWNER_KEY);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.locator('[aria-live="polite"]').first()).toBeAttached();
});

test("reduced motion stops every animation", async ({ browser, baseURL }) => {
  expect(baseURL).toBeDefined();
  const context = await browser.newContext({
    baseURL,
    reducedMotion: "reduce",
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  try {
    await signIn(page);
    const applied = await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    expect(applied, "the harness did not actually request reduced motion").toBe(true);
    await page.goto("/#/queue");
    await expect(page.getByText(ITEM.first).first()).toBeVisible();
    await page.waitForTimeout(400);
    const running = await page.evaluate(() => document.getAnimations().filter((item) => item.playState === "running").length);
    expect(running, "an animation is still running under prefers-reduced-motion").toBe(0);
    const durations = await page.evaluate(() =>
      Array.from(document.querySelectorAll("button, a")).map((node) => getComputedStyle(node).transitionDuration),
    );
    expect(durations.length).toBeGreaterThan(3);
    const tooSlow = durations.filter((value) => value !== "0.01ms" && value !== "0s" && parseFloat(value) >= 0.05);
    expect(tooSlow, `slow transitions survived reduced motion: ${tooSlow.join(", ")}`).toEqual([]);
  } finally {
    await context.close();
  }
});
