import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import ts from "typescript";

/**
 * Transpile the requested `src/api` modules into a staging directory so the Node test
 * runner can import real production code without a bundler or an extra dependency.
 * Extensionless relative specifiers are rewritten because Node ESM requires them.
 */
export async function stageApiModules(temp, names) {
  for (const name of names) {
    const source = await readFile(new URL(`../src/api/${name}.ts`, import.meta.url), "utf8");
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    });
    const file = join(temp, `${name}.js`);
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, withExtensions(outputText));
  }
}

function withExtensions(code) {
  return code.replace(/from "(\.[^"]*)"/g, (match, specifier) =>
    /\.[A-Za-z][A-Za-z0-9]*$/.test(specifier) ? match : `from "${specifier}.js"`,
  );
}
