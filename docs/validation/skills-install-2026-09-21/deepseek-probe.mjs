// Exercise the installed official Harness plugins without a model or API key.
// Usage: node deepseek-probe.mjs DSH_PACKAGE_ROOT PROJECT_ROOT
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [dshRoot, projectRoot] = process.argv.slice(2).map(path => resolve(path));
const load = async (name) => import(pathToFileURL(
  resolve(dshRoot, "node_modules/@deepseek-ai", name, "lib/index.js"),
));
const { Context } = await load("cordis");
const context = new Context();
const fibers = [];
const mount = async (plugin, config) => {
  const fiber = context.plugin(plugin, config);
  fibers.push(fiber);
  await fiber;
};
try {
  await mount((await load("dsh-system-prompt")).default);
  await mount((await load("dsh-tools")).default);
  await mount((await load("dsh-skill")).default);
  await mount(await load("dsh-skill-filesystem"), {
    watch: false, dshHome: resolve(projectRoot, "unused-dsh-home"),
    agentsHome: resolve(projectRoot, "unused-agents-home"),
  });
  const patches = JSON.parse(await readFile(resolve(projectRoot, ".dsh/ken.cordis.json"), "utf8"));
  const entry = patches.flatMap(p => p.insert ?? []).find(p => p.id === "ken-mcp");
  await mount(await load("dsh-mcp-client"), {
    ...entry.config, failOnStartupError: true, reconnect: { enabled: false },
  });
  const names = context.tools.schemas().map(t => t.name).filter(n => n.startsWith("mcp__ken__"));
  for (const name of ["who", "find", "read", "related", "rule", "check", "recall", "remember"]) {
    assert(names.includes(`mcp__ken__ken_${name}`), name);
  }
  const skills = (await context.skills.list({ cwd: projectRoot })).filter(s => s.name.startsWith("ken-"));
  assert.equal(skills.length, 8);
  const definition = await context.skills.get("ken-prevent-regressions", { cwd: projectRoot });
  assert(definition.content.includes("references/return-contract.json"));
  const result = await context.tools.get("mcp__ken__ken_find").execute(
    { query: "CACHE_DIR", scope: "text", literal: true },
    { signal: AbortSignal.timeout(15000) },
  );
  const text = result.content.filter(c => c.type === "text").map(c => c.text).join("\n");
  assert(text.includes("src/storage.py"), text);
  console.log(JSON.stringify({
    dshVersion: JSON.parse(await readFile(resolve(dshRoot, "package.json"))).version,
    tools: names, skills: skills.map(s => ({ name: s.name, source: s.source })),
    call: { tool: "mcp__ken__ken_find", passed: true, result: JSON.parse(text) },
    modelCalls: 0,
  }, null, 2));
} finally {
  for (const fiber of fibers.reverse()) await fiber.dispose();
}
