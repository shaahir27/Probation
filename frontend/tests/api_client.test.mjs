import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { stageApiModules } from "./stage.mjs";

const temp = await mkdtemp(join(tmpdir(), "probation-api-client-"));
await writeFile(join(temp, "package.json"), '{"type":"module"}');
await stageApiModules(temp, ["client", "validation"]);
const { apiClient, setOwnerToken, conflictCode, ApiError } = await import(pathToFileURL(join(temp, "client.js")).href);

test("a 409 conflict keeps the server's semantic reason, not the numeric status", async () => {
  globalThis.fetch = async () => new Response(
    JSON.stringify({ error: { code: "409", message: "initial_decision_already_recorded" } }),
    { status: 409, headers: { "content-type": "application/json" } },
  );
  setOwnerToken("synthetic-owner-key");
  let thrown = null;
  try {
    await apiClient.respondQueue("prop-1", { version: "v2", response: "accept", request_id: "r", reviewed_payload_hash: "h" });
  } catch (error) {
    thrown = error;
  }
  assert.ok(thrown instanceof ApiError, "a 409 must surface a typed ApiError, not a silent success");
  assert.equal(thrown.status, 409);
  assert.equal(thrown.code, "409", "the frozen envelope keeps the numeric status in code");
  assert.equal(conflictCode(thrown), "initial_decision_already_recorded");
  assert.equal(conflictCode(new ApiError("409", "some other reason", 409)), "some other reason");
  assert.equal(conflictCode(new ApiError("409", "409", 409)), "conflict");
  assert.equal(conflictCode(new ApiError("review_binding_changed", "x", 403)), null);
});

const originalFetch = globalThis.fetch;
after(async () => {
  globalThis.fetch = originalFetch;
  setOwnerToken(null);
  const target = resolve(temp);
  assert.equal(dirname(target), resolve(tmpdir()));
  assert.ok(basename(target).startsWith("probation-api-client-"));
  await rm(target, { recursive: true, force: true });
});

test("bootstrap is public and private reads send only the memory token to same origin", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(url.endsWith("bootstrap")
      ? { version: "v1", profile: "private", auth_required: true }
      : { items: [], digests: [], total_count: 0 }), { status: 200 });
  };
  setOwnerToken(null);
  assert.equal((await apiClient.getBootstrap()).profile, "private");
  assert.equal(calls[0].url, "/api/bootstrap");
  assert.equal(calls[0].options.headers.get("Authorization"), null);
  setOwnerToken("synthetic-owner-key");
  await apiClient.getQueue();
  assert.equal(calls[1].url, "/api/queue");
  assert.equal(calls[1].options.headers.get("Authorization"), "Bearer synthetic-owner-key");
  assert.equal(calls[1].options.credentials, "same-origin");
});

test("review is explicitly bound and a 202 response remains queued", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/review")) return new Response(JSON.stringify({ version: "v2", proposal_id: "p1", reviewed_payload: {}, reviewed_payload_hash: "a".repeat(64) }), { status: 200 });
    return new Response(JSON.stringify({ ok: true, response: "accept", request_id: "req-1", id: "req-1", status: "recorded", status_url: "/api/responses/req-1" }), { status: 202 });
  };
  const body = { version: "v2", response: "accept" };
  const reviewed = await apiClient.reviewQueue("p1", body);
  const result = await apiClient.respondQueue("p1", { ...body, request_id: "req-1", reviewed_payload_hash: reviewed.reviewed_payload_hash });
  assert.equal(calls[0].url, "/api/queue/p1/review");
  assert.equal(calls[1].url, "/api/queue/p1/respond");
  assert.equal(JSON.parse(calls[1].options.body).reviewed_payload_hash, "a".repeat(64));
  assert.equal(result.status, "recorded");
  assert.equal(result.request_id, "req-1");
});

test("unconfigured owner API errors show plain sign-in guidance instead of the API code", async () => {
  setOwnerToken("synthetic-test-key");
  globalThis.fetch = async () => new Response(JSON.stringify({
    error: { code: "503", message: "connector_api_not_configured" },
  }), { status: 503 });
  await assert.rejects(apiClient.getQueue(), (error) => {
    assert.equal(error.code, "connector_api_not_configured");
    assert.equal(error.status, 503);
    assert.equal(error.message, "Probation's owner sign-in is not configured yet. Check the backend setup and restart the app.");
    assert.doesNotMatch(error.message, /connector_api_not_configured|503/);
    return true;
  });
});

test("unauthorized response clears the in-memory credential", async () => {
  const calls = [];
  setOwnerToken("temporary-key");
  globalThis.fetch = async (_url, options) => {
    calls.push(options.headers.get("Authorization"));
    return new Response(JSON.stringify({ error: { code: "unauthorized", message: "Sign in again." } }), { status: 401 });
  };
  await assert.rejects(apiClient.getQueue(), { code: "unauthorized", status: 401 });
  globalThis.fetch = async (_url, options) => {
    calls.push(options.headers.get("Authorization"));
    return new Response(JSON.stringify({ items: [], digests: [], total_count: 0 }), { status: 200 });
  };
  await apiClient.getQueue();
  assert.deepEqual(calls, ["Bearer temporary-key", null]);
});
