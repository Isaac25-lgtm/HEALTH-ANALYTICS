/**
 * Pre-build guard for Windows workstations.
 *
 * Next.js 15.5 clears `.next` (except `cache`) at the start of `next build`, and on EPERM/EBUSY
 * it retries forever, so a build directory written by another OS identity makes the build hang
 * silently after the version banner. This guard performs the same clean-up first, with bounded
 * retries, and fails fast with the exact locked paths and an owner command instead.
 *
 * Deletion targets are fixed: only the generated entries directly inside this project's
 * `frontend/.next`, never `cache`, never a symlinked or relocated directory.
 */
import { existsSync, lstatSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const buildDir = path.join(frontend, ".next");

if (path.basename(frontend) !== "frontend" || path.basename(buildDir) !== ".next") {
  console.error(`prepare-build-dir: refusing unexpected path ${buildDir}`);
  process.exit(2);
}
if (!existsSync(buildDir)) {
  process.exit(0);
}
if (lstatSync(buildDir).isSymbolicLink()) {
  console.error("prepare-build-dir: .next is a link; refusing to clean it.");
  process.exit(2);
}

const locked = [];
for (const entry of readdirSync(buildDir)) {
  if (entry === "cache") {
    continue;
  }
  const target = path.join(buildDir, entry);
  if (path.dirname(target) !== buildDir) {
    continue;
  }
  try {
    rmSync(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
  } catch (error) {
    locked.push({ path: target, code: error.code ?? "unknown" });
  }
}

if (locked.length) {
  console.error("prepare-build-dir: generated build output cannot be removed by this user:");
  for (const item of locked) {
    console.error(`  ${item.code}  ${item.path}`);
  }
  console.error(
    [
      "",
      "These files are usually owned by another account that built the project.",
      "Either move the folder aside (same volume, no deletion needed):",
      `  Move-Item -LiteralPath "${buildDir}" -Destination "<quarantine folder>\.next"`,
      "or, from an elevated PowerShell, take ownership and remove it:",
      `  takeown /F "${buildDir}" /R /D Y`,
      `  icacls "${buildDir}" /grant "%USERNAME%:(OI)(CI)F" /T /C`,
      `  Remove-Item -LiteralPath "${buildDir}" -Recurse -Force`,
    ].join("\n"),
  );
  process.exit(1);
}
