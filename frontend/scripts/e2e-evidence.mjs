#!/usr/bin/env node
/**
 * Explicitly refresh the tracked acceptance screenshots in docs/evidence/screenshots/ by running
 * the same no-hang gate with UPDATE_VISUAL_EVIDENCE=1. Only files under that folder may change.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const gate = path.join(path.dirname(fileURLToPath(import.meta.url)), "e2e-gate.mjs");
const result = spawnSync(process.execPath, [gate, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, UPDATE_VISUAL_EVIDENCE: "1" },
});
process.exit(result.status ?? 1);
