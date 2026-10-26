import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * D6 forbids fixtures in the shipped app: every screen shows real API data or an
 * explicit unavailable state. Tests may keep synthetic rows; production code may not.
 */

function sourceFiles(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) sourceFiles(full, out);
    else if (/\.(ts|tsx)$/.test(full)) out.push(full);
  }
  return out;
}

const forbidden = /(?:from\s+["'][^"']*(?:fixture|mock|stub|sample|dummy|preview)[^"']*["'])|(?:mockData|fixtureRows|fakeData)/i;

test("no production source imports or embeds fixture or mock data", () => {
  const files = sourceFiles(fileURLToPath(new URL("../src", import.meta.url)));
  assert.ok(files.length > 20, `expected the app sources, found ${files.length}`);
  const offenders = files.filter((file) => forbidden.test(readFileSync(file, "utf8")));
  assert.deepEqual(offenders, [], `${offenders.join(", ")} carries fixture data into the app`);
});
