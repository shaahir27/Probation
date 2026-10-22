import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

// Use the existing compiler and Node test runner; no test dependency or live I/O.
const temp = await mkdtemp(join(tmpdir(), "probation-client-"));
await writeFile(join(temp, "package.json"), '{"type":"module"}');
for (const name of ["client", "fixtures"]) {
  const source = await readFile(new URL(`../src/api/${name}.ts`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  }}).outputText.replaceAll('"./fixtures"', '"./fixtures.js"');
  await writeFile(join(temp, `${name}.js`), output);
}
const { apiClient } = await import(pathToFileURL(join(temp, "client.js")).href);
const originalFetch = globalThis.fetch;
after(async () => {
  globalThis.fetch = originalFetch;
  const target = resolve(temp);
  assert.equal(dirname(target), resolve(tmpdir()));
  assert.ok(basename(target).startsWith("probation-client-"));
  await rm(target, { recursive: true, force: true });
});

test("live commands report queued intent and status, never immediate completion", async () => {
  const calls = [];
  const command = { id: "synthetic-command", kind: "run_exam", status: "PENDING", result: null,
    requested_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true, command }), { status: 202 });
  };
  apiClient.setPreviewMode(false);
  const exam = await apiClient.runExam("mail|known", "ARCHIVE", 3);
  assert.equal(exam.command.status, "PENDING");
  assert.equal(JSON.parse(calls[0].options.body).attempt_ordinal, 3);
  assert.equal("run_id" in exam, false);
  const denial = await apiClient.denyHabit("synthetic/habit");
  assert.equal(denial.command.status, "PENDING");
  assert.equal(calls[1].url, "/api/habits/synthetic%2Fhabit/deny");
  assert.equal("denied" in denial, false);
  assert.equal((await apiClient.getCommand(command.id)).command.id, command.id);
});

test("preview administration never calls live endpoints", async () => {
  apiClient.setPreviewMode(true);
  globalThis.fetch = () => { throw new Error("Preview reached live fetch"); };
  assert.equal((await apiClient.denyHabit("synthetic")).command.status, "SUCCEEDED");
  assert.equal((await apiClient.runExam("mail|known", "ARCHIVE")).command.status, "SUCCEEDED");
  await assert.rejects(apiClient.getCommand("synthetic"), /Preview/);
  apiClient.setPreviewMode(false);
});

test("polling preserves a typed failure instead of inventing a result", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ error: { code: "503", message: "Unavailable" } }), { status: 503 });
  await assert.rejects(apiClient.getCommand("synthetic"), { code: "503", message: "Unavailable" });
});
