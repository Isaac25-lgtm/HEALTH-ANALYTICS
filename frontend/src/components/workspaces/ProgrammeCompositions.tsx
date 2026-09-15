"use client";

import { RankingPanel, TrendPanel } from "../panels/AnalysisPanels";
import { DownloadsBar } from "../panels/DownloadsBar";
import { InsightsPanel } from "../panels/InsightsPanel";
import { KpiStrip } from "../panels/KpiStrip";
import { ContinuumPanel, MpdsrCausePanel } from "../panels/ProgrammePanels";
import { QualityFlagsPanel } from "../panels/QualityPanels";
import { ScorecardPanel } from "../panels/ScorecardPanels";
import type { CompositionProps } from "./types";

/** ANC and MNCH: the ANC contact indicators beside the unit comparison, with trend and ranking. */
export function AncWorkspace({ dashboard, screen, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-programme">
      <KpiStrip dashboard={dashboard} />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="ANC indicator scorecard"
        defaultView="indicators"
        className="area-a"
      />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="ANC coverage by unit"
        defaultView="units"
        className="area-b"
      />
      <InsightsPanel dashboard={dashboard} viewAllHref={hrefFor({ workspace: "quality" })} className="area-c" />
      <TrendPanel dashboard={dashboard} title="ANC trends" className="area-d" />
      <RankingPanel dashboard={dashboard} className="area-e" />
      <DownloadsBar dashboard={dashboard} />
    </div>
  );
}

/** Intrapartum and newborn: outcomes scorecard and trend first; counts stay unclassified by the server. */
export function IntrapartumWorkspace({ dashboard, screen, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-programme">
      <KpiStrip dashboard={dashboard} />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Intrapartum and newborn scorecard"
        defaultView="indicators"
        className="area-a"
      />
      <TrendPanel dashboard={dashboard} title="Delivery and outcome trends" className="area-b" />
      <InsightsPanel dashboard={dashboard} viewAllHref={hrefFor({ workspace: "quality" })} className="area-c" />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Performance by unit"
        defaultView="units"
        className="area-d"
      />
      <QualityFlagsPanel dashboard={dashboard} compact className="area-e" />
      <DownloadsBar dashboard={dashboard} />
    </div>
  );
}

/** Immunisation: the access-to-completion continuum leads; dropout has no invented bands. */
export function ImmunizationWorkspace({ dashboard, screen, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-programme">
      <KpiStrip dashboard={dashboard} />
      <ContinuumPanel dashboard={dashboard} className="area-a" />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Antigen coverage by unit"
        className="area-b"
      />
      <InsightsPanel dashboard={dashboard} viewAllHref={hrefFor({ workspace: "quality" })} className="area-c" />
      <TrendPanel dashboard={dashboard} title="Coverage trends" className="area-d" />
      <RankingPanel dashboard={dashboard} className="area-e" />
      <DownloadsBar dashboard={dashboard} />
    </div>
  );
}

/** MPDSR: notification and review process scorecard, governed cause patterns and data-quality issues. */
export function MpdsrWorkspace({ dashboard, screen, hrefFor, onOpenEvidence }: CompositionProps) {
  return (
    <div className="layout layout-mpdsr">
      <KpiStrip dashboard={dashboard} />
      <ScorecardPanel
        dashboard={dashboard}
        screen={screen}
        hrefFor={hrefFor}
        onOpen={onOpenEvidence}
        title="Notification and review scorecard"
        defaultView="indicators"
        className="area-a"
      />
      <MpdsrCausePanel dashboard={dashboard} className="area-b" />
      <TrendPanel dashboard={dashboard} title="MPDSR process trends" className="area-c" />
      <QualityFlagsPanel dashboard={dashboard} compact className="area-d" />
      <InsightsPanel
        dashboard={dashboard}
        viewAllHref={hrefFor({ workspace: "quality" })}
        title="Key learning"
        limit={3}
        className="area-e"
      />
      <DownloadsBar dashboard={dashboard} />
    </div>
  );
}
