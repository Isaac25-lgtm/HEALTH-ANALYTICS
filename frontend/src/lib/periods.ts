/**
 * Period vocabulary for the period picker. Keys match the backend's canonical period keys exactly:
 * FY2025/26, FY2025/26Q1, 2025, 202506 and custom month ranges written 202411..202512.
 *
 * History starts in July 2020, the first month the national instance reports completely
 * (owner decision D-057). Nothing later than the last closed month is offered except the
 * in-progress financial year, which is labelled as such.
 */

export type PeriodKind = "fy" | "fy_quarter" | "year" | "month" | "range";

export const HISTORY_START = { year: 2020, month: 7 };

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const PERIOD_KIND_LABELS: Record<PeriodKind, string> = {
  fy: "Financial year",
  fy_quarter: "Quarter",
  year: "Calendar year",
  month: "Month",
  range: "Custom range",
};

function fyKey(startYear: number): string {
  return `FY${startYear}/${String(startYear + 1).slice(-2)}`;
}

function currentFyStart(at: Date): number {
  return at.getMonth() >= 6 ? at.getFullYear() : at.getFullYear() - 1;
}

/** The last fully reported month: the month before the current one. */
export function lastClosedMonth(at: Date = new Date()): { year: number; month: number } {
  const month = at.getMonth(); // 0-based, so this is already "previous month" in 1-based terms
  return month === 0 ? { year: at.getFullYear() - 1, month: 12 } : { year: at.getFullYear(), month };
}

export function monthKey(year: number, month: number): string {
  return `${year}${String(month).padStart(2, "0")}`;
}

export function periodKind(key: string): PeriodKind {
  if (/^\d{6}\.\.\d{6}$/.test(key)) return "range";
  if (/^FY\d{4}\/\d{2}Q[1-4]$/i.test(key)) return "fy_quarter";
  if (/^FY\d{4}\/\d{2}$/i.test(key)) return "fy";
  if (/^\d{6}$/.test(key)) return "month";
  if (/^\d{4}$/.test(key)) return "year";
  return "fy";
}

export function monthOptions(at: Date = new Date()): string[] {
  const last = lastClosedMonth(at);
  const keys: string[] = [];
  let { year, month } = HISTORY_START;
  while (year < last.year || (year === last.year && month <= last.month)) {
    keys.push(monthKey(year, month));
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return keys.reverse();
}

export function financialYearOptions(at: Date = new Date()): string[] {
  const keys: string[] = [];
  for (let start = currentFyStart(at); start >= HISTORY_START.year; start -= 1) keys.push(fyKey(start));
  return keys;
}

export function calendarYearOptions(at: Date = new Date()): string[] {
  const last = lastClosedMonth(at);
  const keys: string[] = [];
  // A calendar year is offered once it has started; the current one is labelled in progress.
  for (let year = last.year; year >= HISTORY_START.year + 1; year -= 1) keys.push(String(year));
  return keys;
}

export function quarterOptions(at: Date = new Date()): string[] {
  const last = lastClosedMonth(at);
  const keys: string[] = [];
  for (let start = currentFyStart(at); start >= HISTORY_START.year; start -= 1) {
    for (let quarter = 4; quarter >= 1; quarter -= 1) {
      // FY quarter 1 starts in July of the financial year's start year.
      const firstMonth = 7 + (quarter - 1) * 3;
      const year = firstMonth > 12 ? start + 1 : start;
      const month = firstMonth > 12 ? firstMonth - 12 : firstMonth;
      if (year > last.year || (year === last.year && month > last.month)) continue;
      keys.push(`${fyKey(start)}Q${quarter}`);
    }
  }
  return keys;
}

export function optionsFor(kind: PeriodKind, at: Date = new Date()): string[] {
  switch (kind) {
    case "fy":
      return financialYearOptions(at);
    case "fy_quarter":
      return quarterOptions(at);
    case "year":
      return calendarYearOptions(at);
    case "month":
      return monthOptions(at);
    default:
      return [];
  }
}

function monthLabel(key: string): string {
  const year = Number(key.slice(0, 4));
  const month = Number(key.slice(4, 6));
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

/** Whether the period is still being reported, so it is never mistaken for a complete one. */
export function isInProgress(key: string, at: Date = new Date()): boolean {
  const last = lastClosedMonth(at);
  const lastKey = Number(monthKey(last.year, last.month));
  switch (periodKind(key)) {
    case "fy": {
      const start = Number(key.slice(2, 6));
      return Number(monthKey(start + 1, 6)) > lastKey;
    }
    case "year":
      return Number(monthKey(Number(key), 12)) > lastKey;
    case "fy_quarter": {
      const start = Number(key.slice(2, 6));
      const quarter = Number(key.slice(-1));
      const lastMonth = 7 + quarter * 3 - 1;
      const year = lastMonth > 12 ? start + 1 : start;
      return Number(monthKey(year, lastMonth > 12 ? lastMonth - 12 : lastMonth)) > lastKey;
    }
    case "range":
      return Number(key.slice(8, 14)) > lastKey;
    default:
      return Number(key) > lastKey;
  }
}

export function periodLabel(key: string, at: Date = new Date()): string {
  const suffix = isInProgress(key, at) ? " (in progress)" : "";
  switch (periodKind(key)) {
    case "month":
      return monthLabel(key) + suffix;
    case "range":
      return `${monthLabel(key.slice(0, 6))} – ${monthLabel(key.slice(8, 14))}${suffix}`;
    case "fy_quarter": {
      const start = Number(key.slice(2, 6));
      const quarter = Number(key.slice(-1));
      const first = 7 + (quarter - 1) * 3;
      const firstYear = first > 12 ? start + 1 : start;
      const firstMonth = first > 12 ? first - 12 : first;
      const lastMonth = firstMonth + 2;
      return `${key.slice(0, 9)} Q${quarter} (${MONTH_NAMES[firstMonth - 1]}–${MONTH_NAMES[lastMonth - 1]} ${firstYear})${suffix}`;
    }
    default:
      return key + suffix;
  }
}

/** A compact label for chart axes: "Jul 25", "FY25/26", "Q1 25/26". */
export function shortPeriodLabel(key: string): string {
  switch (periodKind(key)) {
    case "month":
      return `${MONTH_NAMES[Number(key.slice(4, 6)) - 1]} ${key.slice(2, 4)}`;
    case "fy":
      return `FY${key.slice(4, 6)}/${key.slice(7, 9)}`;
    case "fy_quarter":
      return `Q${key.slice(-1)} ${key.slice(4, 6)}/${key.slice(7, 9)}`;
    default:
      return key;
  }
}

/** The same window one year earlier: the comparison the reference screens use. */
export function sameWindowLastYear(key: string): string {
  switch (periodKind(key)) {
    case "fy":
      return fyKey(Number(key.slice(2, 6)) - 1);
    case "fy_quarter":
      return `${fyKey(Number(key.slice(2, 6)) - 1)}${key.slice(-2)}`;
    case "year":
      return String(Number(key) - 1);
    case "month":
      return monthKey(Number(key.slice(0, 4)) - 1, Number(key.slice(4, 6)));
    case "range":
      return `${Number(key.slice(0, 4)) - 1}${key.slice(4, 6)}..${Number(key.slice(8, 12)) - 1}${key.slice(12, 14)}`;
  }
}

export function rangeKey(from: string, to: string): string {
  const [start, end] = from <= to ? [from, to] : [to, from];
  return start === end ? start : `${start}..${end}`;
}

/** Latest fully closed Uganda financial year (July-June): the default analysis period. */
export function latestClosedFinancialYear(at: Date = new Date()): string {
  return fyKey(currentFyStart(at) - 1);
}
