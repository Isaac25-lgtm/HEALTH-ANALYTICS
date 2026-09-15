"use client";

import { AskTheData } from "../dashboard/AskTheData";
import { MapPanel, RankingPanel, TrendPanel } from "../panels/AnalysisPanels";
import { DownloadsBar } from "../panels/DownloadsBar";
import { InsightsPanel } from "../panels/InsightsPanel";
import { KpiStrip } from "../panels/KpiStrip";
import { CatchmentPanel, FacilityIdentity } from "../panels/ProgrammePanels";
import { QualityFlagsPanel } from "../panels/QualityPanels";
import { ScorecardPanel } from "../panels/ScorecardPanels";
import type { CompositionProps } from "./types";

/**
 * National and regional overview: map, prioritised insights and the child-unit scorecard in the
 * main row; trends, ranking and Ask the Data below; governed downloads as a footer.
 * District and sub-county views lead with the facility scorecard instead of a map.
 */
export function GeographyOverview({ dashboard, screen, comparison, hrefFor, onOpenEvidence }: CompositionProps) {
  const facilities = screen === "district" || screen === "sub_county";
  const qualityHref = hrefFor({ workspace: "quality" });
  return (
    <div className={facilities ? "layout layout-facilities" : "layout layout-overview"}>
      <KpiStrip dashboard={dashboard} />
      {facilities ? (
        <>
          <ScorecardPanel
            dashboard={dashboard}
            screen={screen}
            hrefFor={hrefFor}
            onOpen={onOpenEvidence}
            className="area-primary"
          />
          <InsightsPanel dashboard={dashboard} viewAllHref={qualityHref} className="area-insights" />
        </>
      ) : (
        <>
          <MapPanel dashboard={dashboard} comparison={comparison} className="area-map" />
          <InsightsPanel dashboard={dashboard} viewAllHref={qualityHref} className="area-insights" />
          <ScorecardPanel
            dashboard={dashboard}
            screen={screen}
            hrefFor={hrefFor}
            onOpen={onOpenEvidence}
            className="area-scorecard"
          />
        </>
      )}
      <TrendPanel dashboard={dashboard} className="area-trend" />
      <RankingPanel dashboard={dashboard} className="area-ranking" />
      <AskTheData dashboard={dashboard} period={dashboard.period} comparison={comparison} className="area-ask" compact />
      <DownloadsBar dashboard={dashboard} />
    </div>
  );
}

/** Facility profile: identity, KPIs, indicator scorecard, trend and data-quality alerts, catchment workflow. */
export function FacilityProfile({ dashboard, screen, comparison, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-facility">
      <FacilityIdentity dashboard={dashboard} />
      <KpiStrip dashboard={dashboard} />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Indicator scorecard"
        defaultView="indicators"
        className="area-scorecard"
      />
      <TrendPanel dashboard={dashboard} title="Facility trends" className="area-trend" />
      <QualityFlagsPanel dashboard={dashboard} compact className="area-quality" />
      <CatchmentPanel dashboard={dashboard} className="area-catchment" />
      <AskTheData dashboard={dashboard} period={dashboard.period} comparison={comparison} className="area-ask" compact />
      <DownloadsBar dashboard={dashboard} />
    </div>
  );
}
