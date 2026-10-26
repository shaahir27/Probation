import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * D6 browser acceptance harness.
 *
 * Isolation is per run: a run namespace names one throwaway synthetic workspace, one
 * freshly built bundle and one ephemeral loopback port pair per journey. Ports are
 * allocated once and then frozen into the environment, because this module is loaded
 * again inside each worker and a second allocation would point the worker at a port
 * nobody bound.
 *
 * Each journey is a separate project with its own workspace: a durable-mutation
 * journey must never inherit a queue that another journey already answered.
 */

const runId = `${process.pid}${Date.now().toString(36).slice(-4)}`;

function freePort(): number {
  // Synchronous, loopback only, no traffic: reserve an ephemeral port and hand it to
  // the server, which binds it with --strictPort so a collision fails loudly.
  const script =
    "const s=require('net').createServer();s.listen(0,'127.0.0.1',()=>{process.stdout.write(String(s.address().port));s.close()});";
  return Number(execFileSync(process.execPath, ["-e", script], { encoding: "utf8" }).trim());
}

interface Journey {
  name: string;
  items: number;
  files: string[];
  profile?: "private" | "synthetic";
}

const journeys: Journey[] = [
  {
    name: "workspace",
    items: 3,
    files: [
      "01-copy-truth.spec.ts",
      "02-routes.spec.ts",
      "03-responsive.spec.ts",
      "04-keyboard-a11y.spec.ts",
      "05-network-console.spec.ts",
      "06-session-isolation.spec.ts",
      "08-connect-apps.spec.ts",
    ],
  },
  { name: "private-journey", items: 1, files: ["private-workspace.spec.ts"] },
  { name: "durable-journey", items: 2, files: ["07-golden-path.spec.ts"] },
  { name: "synthetic-connections", items: 1, profile: "synthetic", files: ["09-synthetic-connections.spec.ts"] },
];

const requested = process.argv.flatMap((argument, index) => {
  if ((argument === "--project" || argument === "-p") && process.argv[index + 1]) return [process.argv[index + 1]];
  if (argument.startsWith("--project=")) return [argument.slice("--project=".length)];
  return [];
});
const selected = requested.length > 0 ? journeys.filter((journey) => requested.includes(journey.name)) : journeys;

interface Allocation {
  namespace: string;
  apiPort: number;
  webPort: number;
}

const allocated: Record<string, Allocation> = process.env.PROBATION_D6_E2E_PORTS
  ? (JSON.parse(process.env.PROBATION_D6_E2E_PORTS) as Record<string, Allocation>)
  : {};
for (const journey of selected) {
  if (allocated[journey.name]) continue;
  const namespace = `${runId}${journey.name.replace(/[^a-z]/g, "")}`.slice(0, 40);
  allocated[journey.name] = { namespace, apiPort: freePort(), webPort: freePort() };
}
process.env.PROBATION_D6_E2E_PORTS = JSON.stringify(allocated);

const servers = selected.map((journey) => {
  const allocation = allocated[journey.name] as Allocation;
  return {
    journey,
    allocation,
    origin: `http://127.0.0.1:${allocation.webPort}`,
    stopFile: join(tmpdir(), `probation-d6-e2e-stop-${allocation.namespace}-${process.pid}`),
  };
});

process.env.PROBATION_D6_E2E_STOP_FILES = JSON.stringify(servers.map((server) => server.stopFile));

export default defineConfig({
  testDir: "./tests/e2e",
  outputDir: join("..", "data", "checks", `d6-e2e-${servers[0]?.allocation.namespace ?? runId}`),
  globalTeardown: "./tests/e2e/stop-server.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: "list",
  timeout: 60_000,
  expect: { timeout: 8_000 },
  use: {
    ...devices["Desktop Chrome"],
    channel: "chrome",
    // Traces and video are off by default; only a synthetic failure screenshot is kept.
    trace: "off",
    video: "off",
    screenshot: "only-on-failure",
  },
  webServer: servers.map((server) => ({
    command: "python ../scripts/d6_e2e_server.py",
    url: `${server.origin}/`,
    reuseExistingServer: false,
    timeout: 300_000,
    stdout: "pipe" as const,
    stderr: "pipe" as const,
    env: {
      PROBATION_D6_E2E_NAMESPACE: server.allocation.namespace,
      PROBATION_D6_E2E_API_PORT: String(server.allocation.apiPort),
      PROBATION_D6_E2E_WEB_PORT: String(server.allocation.webPort),
      PROBATION_D6_E2E_ITEMS: String(server.journey.items),
      PROBATION_D6_E2E_PROFILE: server.journey.profile ?? "private",
      PROBATION_D6_E2E_STOP_FILE: server.stopFile,
    },
  })),
  projects: servers.map((server) => ({
    name: server.journey.name,
    testMatch: server.journey.files.map((file) => `**/${file}`),
    use: { baseURL: server.origin },
  })),
});
