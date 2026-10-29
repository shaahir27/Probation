import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const temp = await mkdtemp(join(tmpdir(), "probation-navigation-"));
await writeFile(join(temp, "package.json"), '{"type":"module"}');
const source = await readFile(new URL("../src/navigation.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
await writeFile(join(temp, "navigation.js"), output);
const navigation = await import(pathToFileURL(join(temp, "navigation.js")).href);
after(async () => {
  const target = resolve(temp);
  assert.equal(dirname(target), resolve(tmpdir()));
  assert.ok(basename(target).startsWith("probation-navigation-"));
  await rm(target, { recursive: true, force: true });
});

test("routes preserve encoded opaque IDs and reject malformed hashes", () => {
  const route = navigation.parseRoute("#/queue/id%2Fwith%20space");
  assert.deepEqual(route, { page: "item", id: "id/with space" });
  assert.equal(navigation.routeHash(route), "#/queue/id%2Fwith%20space");
  assert.deepEqual(navigation.parseRoute("#/queue/%ZZ"), { page: "not-found" });
  assert.deepEqual(navigation.parseRoute("#/more/unknown"), { page: "not-found" });
});

test("More groups are the only destinations and old URLs remain aliases", () => {
  for (const id of ["evidence", "access", "record"]) {
    assert.deepEqual(navigation.parseRoute(`#/more/${id}`), { page: "more", section: id });
  }
  for (const [legacy, group] of [
    ["insights", "evidence"], ["metrics", "evidence"], ["exams", "evidence"], ["habits", "evidence"],
    ["connections", "access"], ["privacy", "access"], ["usage", "access"],
    ["activity", "record"], ["settings", "record"], ["help", "record"],
  ]) {
    assert.equal(navigation.moreGroupFor(legacy), group);
    assert.deepEqual(navigation.parseRoute(`#/more/${legacy}`), { page: "more", section: legacy });
  }
  assert.equal(navigation.moreTitle(undefined), "More");
  assert.equal(navigation.moreTitle("insights"), "Evidence");
  assert.equal(navigation.moreTitle("connections"), "Access & privacy");
  assert.equal(navigation.moreGroupFor("library"), null);
});
