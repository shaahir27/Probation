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
const { apiClient, conflictCode, ApiError } = await import(pathToFileURL(join(temp, "client.js")).href);

test("a missing demo allowance explains how to recover instead of showing a raw code", async () => {
  globalThis.fetch = async () => new Response(
    JSON.stringify({ error: { code: "503", message: "scope_missing" } }), { status: 503 },
  );
  await assert.rejects(apiClient.demoAnalyze("Subject: Test\nA notice."),
    (error) => error.status === 503 && /allowance/i.test(error.message) && error.message !== "scope_missing");
});

test("a 409 conflict keeps the server's semantic reason, not the numeric status", async () => {
  globalThis.fetch = async () => new Response(
    JSON.stringify({ error: { code: "409", message: "initial_decision_already_recorded" } }),
    { status: 409, headers: { "content-type": "application/json" } },
  );
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
  const target = resolve(temp);
  assert.equal(dirname(target), resolve(tmpdir()));
  assert.ok(basename(target).startsWith("probation-api-client-"));
  await rm(target, { recursive: true, force: true });
});

test("the owner key is sent once and reads rely on the same-origin cookie", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/session")) {
      return new Response(JSON.stringify({ version: "v1", authenticated: true, owner_id: "local-owner", expires_in: 1800 }), { status: 200 });
    }
    if (url.endsWith("bootstrap")) {
      return new Response(JSON.stringify({ version: "v1", profile: "private", auth_required: true }), { status: 200 });
    }
    return new Response(JSON.stringify({ items: [], digests: [], total_count: 0 }), { status: 200 });
  };
  assert.equal((await apiClient.getBootstrap()).profile, "private");
  assert.equal(calls[0].url, "/api/bootstrap");
  assert.equal(calls[0].options.headers.get("Authorization"), null);

  const session = await apiClient.startSession("synthetic-owner-key");
  assert.equal(session.authenticated, true);
  assert.equal(calls[1].url, "/api/session");
  assert.equal(calls[1].options.method, "POST");
  assert.equal(calls[1].options.headers.get("Authorization"), "Bearer synthetic-owner-key");
  assert.equal(calls[1].options.headers.get("X-Probation-CSRF"), "1");

  await apiClient.getSession();
  await apiClient.getQueue();
  assert.equal(calls[2].url, "/api/session");
  assert.equal(calls[2].options.headers.get("Authorization"), null);
  assert.equal(calls[3].url, "/api/queue");
  assert.equal(calls[3].options.headers.get("Authorization"), null);
  assert.equal(calls[3].options.credentials, "same-origin");
  for (const call of calls.slice(2)) {
    assert.doesNotMatch(String(call.options.headers.get("Authorization")), /synthetic-owner-key/);
  }
});

test("an unreadable session response is rejected, never treated as signed in", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ version: "v1", authenticated: true }), { status: 200 });
  await assert.rejects(apiClient.startSession("synthetic-owner-key"), (error) => error.code === "invalid_response");
  globalThis.fetch = async () => new Response(JSON.stringify({ version: "v2", authenticated: true, owner_id: "x", expires_in: 100 }), { status: 200 });
  await assert.rejects(apiClient.getSession(), (error) => error.code === "invalid_response");
  globalThis.fetch = async () => new Response(JSON.stringify({ version: "v1", authenticated: false, owner_id: "leak" }), { status: 200 });
  await assert.rejects(apiClient.getSession(), (error) => error.code === "invalid_response");
  globalThis.fetch = async () => new Response(JSON.stringify({ version: "v1", authenticated: false }), { status: 200 });
  assert.equal((await apiClient.getSession()).authenticated, false);
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
  assert.equal(calls[0].options.headers.get("X-Probation-CSRF"), "1");
  assert.equal(calls[1].url, "/api/queue/p1/respond");
  assert.equal(JSON.parse(calls[1].options.body).reviewed_payload_hash, "a".repeat(64));
  assert.equal(result.status, "recorded");
  assert.equal(result.request_id, "req-1");
});

test("unconfigured owner API errors show plain sign-in guidance instead of the API code", async () => {
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

test("unsafe requests carry the CSRF marker and safe reads do not", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ items: [], digests: [], total_count: 0 }), { status: 200 });
  };
  await apiClient.getQueue();
  await apiClient.endSession();
  assert.equal(calls[0].options.headers.get("X-Probation-CSRF"), null);
  assert.equal(calls[1].options.method, "DELETE");
  assert.equal(calls[1].options.headers.get("X-Probation-CSRF"), "1");
  assert.equal(calls[1].options.headers.get("Authorization"), null);
});

test("connection access controls use the durable command path and reject invented state", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/api/gmail/connections")) {
      return new Response(JSON.stringify({
        connections: [{ connection_id: "c1", connection_ref: "ref-1", state: "ACTIVE" }],
      }), { status: 200 });
    }
    if (url.endsWith("/commands")) {
      return new Response(JSON.stringify({
        request_id: "cmd-1", command: "pause", status: "recorded", status_url: "/api/commands/cmd-1",
      }), { status: 202 });
    }
    return new Response(JSON.stringify({
      request_id: "cmd-1", type: "pause", status: "succeeded", safe_code: null,
    }), { status: 200 });
  };

  const list = await apiClient.getGmailConnections();
  assert.equal(list.connections[0].connection_ref, "ref-1");
  const receipt = await apiClient.submitGmailConnectionCommand("ref-1", "cmd-1", "pause");
  assert.equal(receipt.status, "recorded");
  assert.equal(calls[1].url, "/api/gmail/connections/ref-1/commands");
  assert.equal(calls[1].options.headers.get("X-Probation-CSRF"), "1");
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    version: "v1", request_id: "cmd-1", command: "pause",
  });
  const status = await apiClient.getGmailLifecycleStatus("cmd-1");
  assert.equal(status.status, "succeeded");
  assert.equal(calls[2].url, "/api/commands/cmd-1");

  globalThis.fetch = async () => new Response(JSON.stringify({ connections: [{ connection_id: "c1" }] }), { status: 200 });
  await assert.rejects(apiClient.getGmailConnections(), (error) => error.code === "invalid_response");
  globalThis.fetch = async () => new Response(JSON.stringify({
    request_id: "cmd-1", command: "pause", status: "recorded", status_url: 7,
  }), { status: 202 });
  await assert.rejects(
    apiClient.submitGmailConnectionCommand("ref-1", "cmd-1", "pause"),
    (error) => error.code === "invalid_response",
  );
});

test("Gmail setup uses a versioned authenticated request and rejects invented connection state", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ version: "v1", request_id: "setup-1", status: "awaiting_consent", connected: false }), { status: 202 });
  };
  assert.equal((await apiClient.startGmailSetup("setup-1")).connected, false);
  assert.equal(calls[0].url, "/api/gmail/setup/read");
  assert.equal(calls[0].options.headers.get("Authorization"), null);
  assert.equal(calls[0].options.headers.get("X-Probation-CSRF"), "1");
  assert.deepEqual(JSON.parse(calls[0].options.body), { version: "v1", request_id: "setup-1" });
  globalThis.fetch = async () => new Response(JSON.stringify({ version: "v1", status: "awaiting_consent", connected: true }));
  await assert.rejects(apiClient.getGmailSetup(), (error) => error.code === "invalid_response");
  globalThis.fetch = async () => new Response(JSON.stringify({ version: "v1", status: "connected", connected: "yes" }));
  await assert.rejects(apiClient.getGmailSetup(), (error) => error.code === "invalid_response");
});
