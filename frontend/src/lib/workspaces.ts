/**
 * Workspace registry: navigation labels, the programme module a workspace pins, and the name of
 * the composition component that lays it out (see components/workspaces/registry.tsx).
 *
 * Every composition reads the same typed, server-calculated snapshot. Compositions differ in
 * which analytical panels they build from the shared primitives and how they arrange them.
 * Nothing here calculates, filters by permission or decides a threshold; the server remains the
 * only authority on what a user may see.
 */

export type CompositionKey =
  | "geography"
  | "facility"
  | "anc"
  | "intrapartum"
  | "immunization"
  | "mpdsr"
  | "maps"
  | "trends"
  | "quality"
  | "reports"
  | "ai"
  | "admin";

export type WorkspaceSpec = {
  slug: string;
  label: string;
  /** Programme module the workspace pins, when it is a programme workspace. */
  module?: string;
  summary: string;
  composition: CompositionKey;
};

export const WORKSPACES: Record<string, WorkspaceSpec> = {
  anc: {
    slug: "anc",
    label: "ANC and MNCH",
    module: "anc",
    summary: "Antenatal coverage, contact retention and the ANC scorecard for the selected geography.",
    composition: "anc",
  },
  intrapartum: {
    slug: "intrapartum",
    label: "Intrapartum and newborn",
    module: "intrapartum",
    summary: "Institutional delivery, perinatal outcomes and newborn care, with counts kept unclassified.",
    composition: "intrapartum",
  },
  immunization: {
    slug: "immunization",
    label: "Immunisation",
    module: "immunization",
    summary:
      "Antigen coverage and the access-to-completion continuum. Dropout stays unclassified until approved bands exist.",
    composition: "immunization",
  },
  mpdsr: {
    slug: "mpdsr",
    label: "MPDSR",
    module: "mpdsr",
    summary:
      "Notification and review process measures. Death counts are burden measures and are never given a RAG verdict.",
    composition: "mpdsr",
  },
  maps: {
    slug: "maps",
    label: "Maps",
    summary: "The authorised snapshot cohort rendered at one coherent geography level.",
    composition: "maps",
  },
  trends: {
    slug: "trends",
    label: "Trends",
    summary: "Period-over-period movement for the selected indicator, interpreted by the server.",
    composition: "trends",
  },
  quality: {
    slug: "quality",
    label: "Data quality",
    summary: "Open flags and the evidence behind them, so reporting problems are not read as performance.",
    composition: "quality",
  },
  reports: {
    slug: "reports",
    label: "Reports and exports",
    summary: "Generate files from the displayed snapshot and follow the queue through to a download.",
    composition: "reports",
  },
  ai: {
    slug: "ai",
    label: "AI insights",
    summary: "Questions answered only from the verified evidence package for this snapshot.",
    composition: "ai",
  },
  admin: {
    slug: "admin",
    label: "Administration",
    summary: "Governed registries: populations, geography, mappings, providers and system health.",
    composition: "admin",
  },
};

export function workspaceSpec(slug?: string | null): WorkspaceSpec | null {
  if (!slug) {
    return null;
  }
  return WORKSPACES[slug] ?? null;
}

/** The composition for a workspace, or the geography screen's own composition. */
export function compositionFor(screen: string, slug?: string | null): CompositionKey {
  const spec = workspaceSpec(slug);
  if (spec) {
    return spec.composition;
  }
  return screen === "facility" ? "facility" : "geography";
}

export function moduleFor(slug?: string | null): string | undefined {
  return workspaceSpec(slug)?.module;
}

export const SCREEN_TITLES: Record<string, string> = {
  national: "National overview",
  regional: "Regional overview",
  district: "District facility performance",
  sub_county: "Sub-county facility performance",
  facility: "Facility performance profile",
};
