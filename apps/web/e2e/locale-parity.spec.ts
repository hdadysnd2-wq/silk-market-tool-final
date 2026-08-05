import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// I10 guard: every UI string must exist in BOTH messages/ar.json and en.json.
// A key present in one but not the other means a locale renders a raw key or
// falls back to the wrong language — so the two key sets must be identical.
// Playwright runs with cwd = apps/web (the config's directory).
const messagesDir = join(process.cwd(), "messages");

function keySet(obj: unknown, prefix = "", out = new Set<string>()): Set<string> {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj)) {
      const key = prefix ? `${prefix}.${k}` : k;
      out.add(key);
      keySet(v, key, out);
    }
  }
  return out;
}

test("ar.json and en.json expose identical key sets (I10)", () => {
  const en = JSON.parse(readFileSync(join(messagesDir, "en.json"), "utf-8"));
  const ar = JSON.parse(readFileSync(join(messagesDir, "ar.json"), "utf-8"));
  const enKeys = keySet(en);
  const arKeys = keySet(ar);

  const missingInAr = [...enKeys].filter((k) => !arKeys.has(k)).sort();
  const missingInEn = [...arKeys].filter((k) => !enKeys.has(k)).sort();

  expect(missingInAr, `keys in en.json missing from ar.json: ${missingInAr.join(", ")}`).toEqual(
    [],
  );
  expect(missingInEn, `keys in ar.json missing from en.json: ${missingInEn.join(", ")}`).toEqual(
    [],
  );
});
