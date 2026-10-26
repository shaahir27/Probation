import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { stageApiModules } from "./stage.mjs";

// Use the existing compiler and Node test runner; no test dependency or live I/O.
const temp = await mkdtemp(join(tmpdir(), "probation-client-"));
await writeFile(join(temp, "package.json"), '{"type":"module"}');
await stageApiModules(temp, ["client", "validation"]);
const { apiClient } = await import(pathToFileURL(join(temp, "client.js")).href);
const originalFetch = globalThis.fetch;
after(async () => {
  globalThis.fetch = originalFetch;
  const target = resolve(temp);
  assert.equal(dirname(target), resolve(tmpdir()));
  assert.ok(basename(target).startsWith("probation-client-"));
  await rm(target, { recursive: true, force: true });
});

test("admin commands report queued intent and status, never immediate completion", async () => {
  const calls = [];
  const command = { id: "synthetic-command", kind: "run_exam", status: "PENDING", result: null,
    requested_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true, command }), { status: 202 });
  };
  const exam = await apiClient.runExam("mail|known", "ARCHIVE", 3);
  assert.equal(exam.command.status, "PENDING");
  assert.equal(JSON.parse(calls[0].options.body).attempt_ordinal, 3);
  assert.equal("run_id" in exam, false);
  const denial = await apiClient.denyHabit("synthetic/habit", "request-deny-1");
  assert.equal(denial.command.status, "PENDING");
  assert.equal(calls[1].url, "/api/habits/synthetic%2Fhabit/deny");
  assert.equal("denied" in denial, false);
  assert.equal((await apiClient.getCommand(command.id)).command.id, command.id);
});

test("the client has no preview mode that can fake an admin success", async () => {
  assert.equal("setPreviewMode" in apiClient, false);
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true, command: { id: "cmd-1", kind: "run_exam", status: "PENDING",
      requested_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", result: null } }), { status: 202 });
  };
  const response = await apiClient.runExam("mail|known", "ARCHIVE");
  assert.equal(response.command.status, "PENDING");
  assert.equal(calls.length, 1);
});

test("polling preserves a typed failure instead of inventing a result", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ error: { code: "503", message: "Unavailable" } }), { status: 503 });
  await assert.rejects(apiClient.getCommand("synthetic"), { code: "503", message: "Unavailable" });
});
