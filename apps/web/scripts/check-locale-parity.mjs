// I10 guard — the ar/en message catalogs must stay structurally identical.
// Fails when a key exists in one locale but not the other, or when a message's
// ICU placeholders ({n}, {name}, …) differ between locales. Wired into the web
// CI job so an English-only (or Arabic-only) regression cannot ship green.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const load = (locale) => JSON.parse(readFileSync(join(root, "messages", `${locale}.json`), "utf8"));

function flatten(obj, prefix = "", out = new Map()) {
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object") flatten(value, path, out);
    else out.set(path, String(value));
  }
  return out;
}

const placeholders = (msg) =>
  [...msg.matchAll(/\{(\w+)(?:,[^}]*)?\}/g)].map((m) => m[1]).sort().join(",");

const ar = flatten(load("ar"));
const en = flatten(load("en"));

const errors = [];
for (const key of ar.keys()) if (!en.has(key)) errors.push(`missing in en.json: ${key}`);
for (const key of en.keys()) if (!ar.has(key)) errors.push(`missing in ar.json: ${key}`);
for (const [key, msg] of ar) {
  if (!en.has(key)) continue;
  const a = placeholders(msg);
  const b = placeholders(en.get(key));
  if (a !== b) errors.push(`placeholder mismatch at ${key}: ar={${a}} en={${b}}`);
}

if (errors.length) {
  console.error(`Locale parity check FAILED (${errors.length} problem(s)):`);
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}
console.log(`Locale parity OK — ${ar.size} keys identical across ar/en.`);
