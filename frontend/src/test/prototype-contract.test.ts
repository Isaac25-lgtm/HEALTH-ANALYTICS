import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Work package L: the HTML prototype is a visual reference only. Its sample values, client-side
 * calculations, invented thresholds and hosted fonts must never reach production frontend code.
 */
const SRC = path.resolve(__dirname, "..");

function productionFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      return entry === "test" ? [] : productionFiles(full);
    }
    return /\.(tsx?|css)$/.test(entry) ? [full] : [];
  });
}

const FORBIDDEN: Array<[RegExp, string]> = [
  [/fonts\.googleapis|fonts\.gstatic/, "hosted Google fonts"],
  [/compositeScore|composite_score/, "prototype composite score"],
  [/synthBase|valueOf\(geo|POPULATION_REGISTRY|DISTRICT_BY_CODE/, "prototype data helpers"],
  [/\bfullimm\b|\bu5mr\b/, "prototype indicators"],
  [/1\.032/, "prototype growth-rate divisor"],
  [/green:\s*90\s*,\s*amber:\s*75/, "invented EPI bands"],
  [/population\s*\*\s*0\.0|\*\s*coefficient|periodFraction/, "client-side denominator calculation"],
  [/numerator\s*\/\s*denominator/, "client-side indicator calculation"],
  [/national\.analyst/, "prefilled synthetic account"],
  [/\*\s*100(?![\d.])/, "client-side percentage calculation"],
  [/raw_value\s*[-+]\s*[\w.?]*raw_value/, "client-side change calculation"],
  [/reduce\([^)]*raw_value/, "client-side aggregation of indicator values"],
  [/(?:NATIONAL|REGION|DISTRICT)_TARGETS?\s*=|green_min\s*:\s*\d/, "client-side thresholds"],
];

describe("prototype contract", () => {
  const files = productionFiles(SRC);

  it("scans real production source", () => {
    expect(files.length).toBeGreaterThan(15);
  });

  for (const [pattern, label] of FORBIDDEN) {
    it(`contains no ${label}`, () => {
      const offenders = files.filter((file) => pattern.test(readFileSync(file, "utf8")));
      expect(offenders.map((file) => path.relative(SRC, file))).toEqual([]);
    });
  }

  it("contains no hard-coded population figures", () => {
    const literals = ["45905417", "45,905,417", "248910", "248,910", "240159"];
    const offenders = files.filter((file) => literals.some((value) => readFileSync(file, "utf8").includes(value)));
    expect(offenders).toEqual([]);
  });
});
