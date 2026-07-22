#!/usr/bin/env node
/**
 * Detects a stale `types/generated-api.ts` relative to the checked-in
 * `openapi/finquest-api.json` - regenerates into a temp file with the
 * exact same `openapi-typescript` invocation as `npm run api:generate`
 * and diffs it against the committed file. Never edits the committed
 * file itself; never talks to a live backend.
 *
 * Exit 0: types are current. Exit 1: stale (with instructions).
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const openapiPath = join(frontendRoot, "openapi", "finquest-api.json");
const committedTypesPath = join(frontendRoot, "types", "generated-api.ts");

if (!existsSync(openapiPath)) {
  console.error(`Missing ${openapiPath} - run "npm run api:export" first.`);
  process.exit(1);
}
if (!existsSync(committedTypesPath)) {
  console.error(`Missing ${committedTypesPath} - run "npm run api:generate" first.`);
  process.exit(1);
}

const tempDir = mkdtempSync(join(tmpdir(), "finquest-openapi-check-"));
const tempOutputPath = join(tempDir, "generated-api.ts");

try {
  execFileSync(
    "node",
    [
      join(frontendRoot, "node_modules", "openapi-typescript", "bin", "cli.js"),
      openapiPath,
      "-o",
      tempOutputPath,
    ],
    { cwd: frontendRoot, stdio: "inherit" }
  );

  const fresh = readFileSync(tempOutputPath, "utf-8");
  const committed = readFileSync(committedTypesPath, "utf-8");

  if (fresh !== committed) {
    console.error(
      "\ntypes/generated-api.ts is STALE relative to openapi/finquest-api.json.\n" +
        "Run: npm run api:export && npm run api:generate\n"
    );
    process.exit(1);
  }

  console.log("types/generated-api.ts is up to date with openapi/finquest-api.json.");
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
