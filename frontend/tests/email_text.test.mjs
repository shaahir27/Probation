import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { stageApiModules } from "./stage.mjs";

const temp = await mkdtemp(join(tmpdir(), "probation-email-text-"));
await writeFile(join(temp, "package.json"), '{"type":"module"}');
await stageApiModules(temp, ["emailText"], "lib");
const { formatWhen, parseEmailText, senderDisplay } = await import(
  pathToFileURL(join(temp, "emailText.js")).href
);

after(async () => {
  await rm(temp, { recursive: true, force: true });
});

test("a live summary becomes a clean subject, preview and body without the disclaimer wall", () => {
  const summary = [
    "Subject: [SYNTHETIC TEST] Demo workflow 2026-10-27",
    "",
    "Synthetic test only. No real event, payment, or personal information is involved. Keep this message for the demo.",
    "-- ::DISCLAIMER: ---------------------------------------------------------------------",
    "The contents of this e-mail are confidential. <<URL:https://example.invalid>>",
  ].join("\n");
  const parsed = parseEmailText(summary);
  assert.equal(parsed.subject, "[SYNTHETIC TEST] Demo workflow 2026-10-27");
  assert.match(parsed.preview, /^Synthetic test only/);
  assert.doesNotMatch(parsed.preview, /DISCLAIMER|confidential/);
  assert.match(parsed.body, /^Synthetic test only/);
  assert.doesNotMatch(parsed.body, /DISCLAIMER|confidential|URL:/);
  assert.match(parsed.disclaimer ?? "", /confidential/);
  assert.doesNotMatch(parsed.disclaimer ?? "", /<<URL:/);
});

test("plain summaries keep the first line as the subject and the remaining text as a preview", () => {
  const parsed = parseEmailText("Some information.\n\nA little more context.");
  assert.equal(parsed.subject, "Some information.");
  assert.equal(parsed.preview, "A little more context.");
  assert.equal(parsed.body, "A little more context.");
  assert.equal(parsed.disclaimer, null);
});

test("dates are readable and long sender addresses are shortened without losing the domain", () => {
  assert.match(formatWhen("2026-10-27T18:42:04.790017Z"), /2026/);
  assert.doesNotMatch(formatWhen("2026-10-27T18:42:04.790017Z"), /T18:42:04/);
  assert.equal(formatWhen(null), "Not recorded");
  assert.equal(senderDisplay("alice@example.test"), "alice@example.test");
  const shortened = senderDisplay("shaahirmeeranmohaideen2510883@ssn.edu.in");
  assert.match(shortened, /…@ssn\.edu\.in$/);
  assert.ok(shortened.length < "shaahirmeeranmohaideen2510883@ssn.edu.in".length);
});
