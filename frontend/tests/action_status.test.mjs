import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { stageApiModules } from "./stage.mjs";

const temp = await mkdtemp(join(tmpdir(), "probation-action-status-"));
await writeFile(join(temp, "package.json"), '{"type":"module"}');
await stageApiModules(temp, ["action_status"]);
const { actionStatusLabel, isConfirmedComplete, isSettledStatus, isUnconfirmedResult } = await import(
  pathToFileURL(join(temp, "action_status.js")).href
);

after(async () => {
  await rm(temp, { recursive: true, force: true });
});

test("a completed undo is settled rather than still waiting", () => {
  assert.equal(actionStatusLabel("UNDONE"), "Undone");
  assert.equal(isSettledStatus("UNDONE"), true);
  assert.equal(isSettledStatus("done"), true);
  assert.equal(isSettledStatus("CANCELLED"), true);
  assert.equal(isSettledStatus("PENDING"), false);
  assert.equal(isConfirmedComplete("UNDONE"), false);
});

test("unconfirmed provider results never read as settled", () => {
  assert.equal(isUnconfirmedResult("unknown"), true);
  assert.equal(isUnconfirmedResult("needs-reconciliation"), true);
  assert.equal(isSettledStatus("unknown"), false);
  assert.equal(actionStatusLabel("unknown"), "Result not confirmed");
  assert.equal(actionStatusLabel("not-a-status"), "Status unavailable");
});
