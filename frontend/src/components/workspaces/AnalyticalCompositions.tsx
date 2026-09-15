"use client";

import { AskTheData } from "../dashboard/AskTheData";
import { MapPanel, RankingPanel, TrendPanel } from "../panels/AnalysisPanels";
import { DownloadsBar } from "../panels/DownloadsBar";
import { InsightsPanel } from "../panels/InsightsPanel";
import { CatchmentPanel } from "../panels/ProgrammePanels";
import { QualityFlagsPanel, QualitySummary, UnavailableIndicatorsPanel } from "../panels/QualityPanels";
import { ScorecardPanel } from "../panels/ScorecardPanels";
import { AdministrationPanels } from "../ui/AdministrationPanels";
import { ExportHistory } from "../ui/ExportHistory";
import type { CompositionProps } from "./types";

/** Maps: a large map of the snapshot cohort with ranking and the unit values behind the colours. */
export function MapsWorkspace({ dashboard, screen, comparison, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-maps">
      <MapPanel dashboard={dashboard} comparison={comparison} className="area-a" />
      <RankingPanel dashboard={dashboard} className="area-b" />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Mapped unit values"
        className="area-c"
      />
    </div>
  );
}

/** Trends: the selected indicator over time, with the units behind the movement. */
export function TrendsWorkspace({ dashboard, screen, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-trends">
      <TrendPanel dashboard={dashboard} title="Indicator trends" className="area-a" />
      <RankingPanel dashboard={dashboard} className="area-b" />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Current values by unit"
        className="area-c"
      />
      <InsightsPanel dashboard={dashboard} viewAllHref={hrefFor({ workspace: "quality" })} className="area-d" />
    </div>
  );
}

/** Data quality: counts, paginated flags and the reasons indicators have no value. */
export function QualityWorkspace({ dashboard, screen, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-quality">
      <QualitySummary dashboard={dashboard} />
      <QualityFlagsPanel dashboard={dashboard} className="area-a" />
      <UnavailableIndicatorsPanel dashboard={dashboard} className="area-b" />
      <InsightsPanel
        dashboard={dashboard}
        viewAllHref={hrefFor({ workspace: "quality" })}
        title="All priority insights"
        limit={50}
        className="area-c"
      />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Indicator status"
        defaultView="indicators"
        className="area-d"
      />
    </div>
  );
}

/** Reports and exports: governed downloads for this snapshot and the caller's job history. */
export function ReportsWorkspace({ dashboard }: CompositionProps) {
  return (
    <div className="layout layout-reports">
      <DownloadsBar dashboard={dashboard} variant="panel" />
      <ExportHistory className="area-b" />
    </div>
  );
}

/** AI insights: Ask the Data at full size beside the deterministic insight list. */
export function AiWorkspace({ dashboard, comparison, hrefFor }: CompositionProps) {
  return (
    <div className="layout layout-ai">
      <AskTheData dashboard={dashboard} period={dashboard.period} comparison={comparison} className="area-a" />
      <InsightsPanel
        dashboard={dashboard}
        viewAllHref={hrefFor({ workspace: "quality" })}
        limit={8}
        className="area-b"
      />
    </div>
  );
}

/** Administration: registry health and the population workflow. The server enforces the role. */
export function AdminWorkspace({ dashboard, context }: CompositionProps) {
  return (
    <div className="layout layout-admin">
      <AdministrationPanels dashboard={dashboard} context={context} className="area-a" />
      {context.actions.includes("manage_users") ? <CatchmentPanel dashboard={dashboard} className="area-b" /> : null}
    </div>
  );
}
