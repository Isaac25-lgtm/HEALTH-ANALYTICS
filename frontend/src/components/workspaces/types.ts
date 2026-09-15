import type { CurrentContext, DashboardResponse, Measure } from "@/lib/types";

export type LinkTarget = {
  screen?: string;
  orgUnitId?: string;
  workspace?: string;
  module?: string;
};

/** Everything a composition receives. All analytical content comes from `dashboard`. */
export type CompositionProps = {
  dashboard: DashboardResponse;
  context: CurrentContext;
  screen: string;
  comparison?: string;
  onOpenEvidence: (measure: Measure) => void;
  /** Builds a link that preserves period, comparison and module. */
  hrefFor: (target: LinkTarget) => string;
};
