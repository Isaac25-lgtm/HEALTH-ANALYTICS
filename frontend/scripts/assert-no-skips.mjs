import { readFileSync } from "node:fs";

const reportPath = process.argv[2];
if (!reportPath) {
  throw new Error("Usage: node scripts/assert-no-skips.mjs <playwright-json-report>");
}

const report = JSON.parse(readFileSync(reportPath, "utf8"));
const skipped = [];

function visit(value, trail = "report") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => visit(item, `${trail}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  if (value.status === "skipped") skipped.push(trail);
  for (const [key, child] of Object.entries(value)) visit(child, `${trail}.${key}`);
}

visit(report);
if (skipped.length) {
  throw new Error(`Playwright reported ${skipped.length} skipped result(s): ${skipped.join(", ")}`);
}
