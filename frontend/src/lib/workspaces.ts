/**
 * Workspace compositions.
 *
 * Every workspace reads the same typed dashboard snapshot from the server; what differs is
 * which analytical surfaces it shows and in what order. Nothing here calculates, filters by
 * permission, or decides a threshold: hiding a section is presentation, and the server remains
 * the only authority on what a user may see.
 */

export type SectionKey =
  | "identity"
  | "kpis"
  | "continuum"
  | "mpdsr"
  | "map"
  | "insights"
  | "scorecard"
  | "children"
  | "trend"
  | "ranking"
  | "quality"
  | "population"
  | "ask"
  | "exports"
  | "exportHistory"
  | "administration";

export type WorkspaceSpec = {
  slug: string;
  label: string;
  /** Programme module the workspace pins, when it is a programme workspace. */
  module?: string;
  summary: string;
  sections: SectionKey[];
};

const GEOGRAPHY_SECTIONS: SectionKey[] = [
  "identity",
  "kpis",
  "continuum",
  "mpdsr",
  "map",
  "insights",
  "scorecard",
  "children",
  "trend",
  "ranking",
  "population",
  "ask",
  "exports",
];

export const WORKSPACES: Record<string, WorkspaceSpec> = {
  anc: {
    slug: "anc",
    label: "ANC and MNCH",
    module: "anc",
    summary: "Antenatal coverage, contact retention and the ANC scorecard for the selected geography.",
    sections: ["kpis", "scorecard", "children", "trend", "ranking", "insights", "ask", "exports"],
  },
  intrapartum: {
    slug: "intrapartum",
    label: "Intrapartum and newborn",
    module: "intrapartum",
    summary: "Institutional delivery, perinatal outcomes and newborn care, with counts kept unclassified.",
    sections: ["kpis", "scorecard", "children", "trend", "insights", "ask", "exports"],
  },
  immunization: {
    slug: "immunization",
    label: "Immunisation",
    module: "immunization",
    summary:
      "Antigen coverage and the access-to-completion continuum. Dropout stays unclassified until approved bands exist.",
    sections: ["kpis", "continuum", "scorecard", "children", "trend", "insights", "exports"],
  },
  mpdsr: {
    slug: "mpdsr",
    label: "MPDSR",
    module: "mpdsr",
    summary:
      "Notification and review process measures. Death counts are burden measures and are never given a RAG verdict.",
    sections: ["kpis", "mpdsr", "scorecard", "trend", "insights", "exports"],
  },
  maps: {
    slug: "maps",
    label: "Maps",
    summary: "The authorised snapshot cohort rendered at one coherent geography level.",
    sections: ["map", "ranking", "children"],
  },
  trends: {
    slug: "trends",
    label: "Trends",
    summary: "Period-over-period movement for the selected indicator, interpreted by the server.",
    sections: ["trend", "children", "ranking"],
  },
  quality: {
    slug: "quality",
    label: "Data quality",
    summary: "Open flags and the evidence behind them, so reporting problems are not read as performance.",
    sections: ["quality", "insights", "scorecard"],
  },
  reports: {
    slug: "reports",
    label: "Reports and exports",
    summary: "Generate files from the displayed snapshot and follow the queue through to a download.",
    sections: ["exports", "exportHistory"],
  },
  ai: {
    slug: "ai",
    label: "AI insights",
    summary: "Questions answered only from the verified evidence package for this snapshot.",
    sections: ["ask", "insights"],
  },
  admin: {
    slug: "admin",
    label: "Administration",
    summary: "Governed registries: populations, geography, mappings, providers and system health.",
    sections: ["administration", "population"],
  },
};

export function workspaceSpec(slug?: string | null): WorkspaceSpec | null {
  if (!slug) {
    return null;
  }
  return WORKSPACES[slug] ?? null;
}

/** Sections to render for a workspace, or the full geography composition when there is none. */
export function sectionsFor(slug?: string | null): SectionKey[] {
  return workspaceSpec(slug)?.sections ?? GEOGRAPHY_SECTIONS;
}

export function moduleFor(slug?: string | null): string | undefined {
  return workspaceSpec(slug)?.module;
}
