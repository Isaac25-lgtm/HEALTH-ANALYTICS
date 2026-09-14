export const STATUS_META: Record<
  string,
  { label: string; cue: string; className: string }
> = {
  green: { label: "On track", cue: "G", className: "status-green" },
  yellow: { label: "Watch", cue: "Y", className: "status-yellow" },
  red: { label: "Off track", cue: "R", className: "status-red" },
  blue: { label: "Non-assessable", cue: "B", className: "status-blue" },
  n_a: { label: "No approved threshold", cue: "NA", className: "status-na" },
  unclassified: { label: "Unclassified", cue: "U", className: "status-na" },
};

export function resolveStatus(value: {
  quality_status?: string | null;
  status?: string | null;
  performance_status?: string | null;
  raw_value?: number | null;
}): string {
  if (value.quality_status === "blue" || value.status === "blue") {
    return "blue";
  }
  if (value.raw_value === null || value.raw_value === undefined) {
    return "missing";
  }
  return value.status || value.performance_status || "n_a";
}

export function statusMeta(status: string) {
  if (status === "missing") {
    return { label: "No data", cue: "—", className: "status-missing" };
  }
  return STATUS_META[status] ?? STATUS_META.n_a;
}

export function formatMeasure(raw: number | null, unit: string | null, display?: string | null): string {
  if (raw === null || raw === undefined) {
    return "No data";
  }
  if (display) {
    return unit && unit !== "%" && !display.includes(unit) ? `${display} ${unit}` : display;
  }
  if (unit === "count") {
    return String(Math.round(raw));
  }
  const rounded = Number.isInteger(raw) ? String(raw) : raw.toFixed(1);
  return unit ? `${rounded} ${unit}` : rounded;
}

const INTERPRETATION_LABELS: Record<string, string> = {
  improved: "Improved",
  deteriorated: "Deteriorated",
  unchanged: "Unchanged",
  not_interpreted: "Not interpreted",
};

/**
 * The direction of change comes only from the server's approved classification rule.
 * The sign of the numeric change is never used to call a movement better or worse.
 */
export function interpretationLabel(change?: { interpretation?: string | null } | null): string | null {
  if (!change?.interpretation) {
    return null;
  }
  return INTERPRETATION_LABELS[change.interpretation] ?? INTERPRETATION_LABELS.not_interpreted;
}

const MAP_STATE_COPY: Record<string, { title: string; detail: string }> = {
  geometry_unavailable_for_level: {
    title: "Boundaries unavailable for this level",
    detail:
      "No approved boundaries or coordinates exist for the units shown. Shapes from another administrative level are not substituted.",
  },
  mixed_levels_not_mapped: {
    title: "Mixed administrative levels",
    detail: "The value rows span different administrative levels, so they are not drawn on one map.",
  },
  no_map_units: {
    title: "No authorised map units",
    detail: "There are no authorised child units to map for this view.",
  },
  not_available: {
    title: "Map unavailable for this snapshot",
    detail: "This snapshot predates the map cohort contract. Run the analysis again to map it.",
  },
};

export function mapStateCopy(state: string, note?: string | null): { title: string; detail: string } | null {
  if (state === "mapped") {
    return null;
  }
  const copy = MAP_STATE_COPY[state] ?? MAP_STATE_COPY.not_available;
  return { title: copy.title, detail: note ?? copy.detail };
}

export function changeLabel(change?: {
  change_kind?: string | null;
  percentage_point_change?: number | null;
  relative_percent_change?: number | null;
  absolute_change?: number | null;
} | null): string {
  if (!change || change.change_kind == null) {
    return "No comparison";
  }
  if (change.change_kind === "percentage_point" && change.percentage_point_change != null) {
    const value = change.percentage_point_change;
    const sign = value > 0 ? "+" : "";
    return `${sign}${value.toFixed(1)} pp`;
  }
  if (change.absolute_change != null) {
    const value = change.absolute_change;
    const sign = value > 0 ? "+" : "";
    return `${sign}${value.toFixed(1)}`;
  }
  return "No comparison";
}
