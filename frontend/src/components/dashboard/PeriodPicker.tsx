"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  PERIOD_KIND_LABELS,
  type PeriodKind,
  monthOptions,
  optionsFor,
  periodKind,
  periodLabel,
  rangeKey,
} from "@/lib/periods";
import { Icon } from "../ui/Icon";

const KINDS: PeriodKind[] = ["fy", "fy_quarter", "year", "month", "range"];

/**
 * One control for every period shape the platform understands: financial year, FY quarter,
 * calendar year, month and a custom from-to month range. The chosen key is what the backend
 * receives; nothing here computes a value.
 */
export function PeriodPicker({
  value,
  onChange,
  label = "Period",
  name = "period",
}: {
  value: string;
  onChange: (key: string) => void;
  label?: string;
  name?: string;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<PeriodKind>(periodKind(value));
  const months = useMemo(() => monthOptions(), []);
  const [rangeFrom, setRangeFrom] = useState(
    periodKind(value) === "range" ? value.slice(0, 6) : months[Math.min(13, months.length - 1)] ?? months[0],
  );
  const [rangeTo, setRangeTo] = useState(periodKind(value) === "range" ? value.slice(8, 14) : months[0]);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const choose = (key: string) => {
    onChange(key);
    setOpen(false);
  };

  return (
    <div className="filter-field period-picker" ref={root}>
      <span>{label}</span>
      <input type="hidden" name={name} value={value} />
      <button
        type="button"
        className="period-trigger"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Icon name="calendar" size={16} className="field-icon" />
        <span className="period-value">{periodLabel(value)}</span>
        <Icon name="chevron" size={14} />
      </button>
      {open ? (
        <div className="period-panel" role="dialog" aria-label={`Choose ${label.toLowerCase()}`}>
          <div className="period-kinds" role="tablist">
            {KINDS.map((option) => (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={kind === option}
                className={kind === option ? "active" : ""}
                onClick={() => setKind(option)}
              >
                {PERIOD_KIND_LABELS[option]}
              </button>
            ))}
          </div>
          {kind === "range" ? (
            <div className="period-range">
              <label>
                From
                <select value={rangeFrom} onChange={(event) => setRangeFrom(event.target.value)} aria-label="Range start">
                  {[...months].reverse().map((key) => (
                    <option key={key} value={key}>
                      {periodLabel(key)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                To
                <select value={rangeTo} onChange={(event) => setRangeTo(event.target.value)} aria-label="Range end">
                  {[...months].reverse().map((key) => (
                    <option key={key} value={key}>
                      {periodLabel(key)}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="primary-button" onClick={() => choose(rangeKey(rangeFrom, rangeTo))}>
                Use range
              </button>
            </div>
          ) : (
            <ul className="period-options">
              {optionsFor(kind).map((key) => (
                <li key={key}>
                  <button
                    type="button"
                    className={key === value ? "selected" : ""}
                    aria-pressed={key === value}
                    onClick={() => choose(key)}
                  >
                    {periodLabel(key)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
