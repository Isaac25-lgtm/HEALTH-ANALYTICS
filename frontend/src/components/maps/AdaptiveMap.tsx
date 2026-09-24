"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { getSnapshotMapFeatures } from "@/lib/api";
import { mapStateCopy } from "@/lib/status";
import type { DashboardResponse, MapFeatureCollection } from "@/lib/types";
import { NoDataState } from "../ui/EmptyStates";
import { StatusPill } from "../ui/StatusPill";

const MapLibreCanvas = dynamic(() => import("./MapLibreCanvas").then((mod) => mod.MapLibreCanvas), {
  ssr: false,
  loading: () => <p className="muted">Loading MapLibre canvas…</p>,
});

/**
 * Renders exactly the snapshot's map cohort. The server decides the map level, the
 * geometry effective date and every feature value; the client performs no calculation.
 */
export function AdaptiveMap({
  dashboard,
  period,
  comparison,
}: {
  dashboard: DashboardResponse;
  period: string;
  comparison?: string;
}) {
  const [features, setFeatures] = useState<MapFeatureCollection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const block = dashboard.map;
  const snapshotId = dashboard.analysis_snapshot_id;
  const mapState = block?.map_state ?? "not_available";

  useEffect(() => {
    setFeatures(null);
    setError(null);
    if (mapState !== "mapped") {
      return;
    }
    const controller = new AbortController();
    getSnapshotMapFeatures(snapshotId, controller.signal)
      .then(setFeatures)
      .catch((err: Error & { name?: string }) => {
        if (err.name !== "AbortError") {
          setError(err.message);
        }
      });
    return () => controller.abort();
  }, [mapState, snapshotId]);

  const indicatorName =
    dashboard.module_result.indicators.find((row) => row.indicator_code === block?.selected_indicator)?.name ??
    block?.selected_indicator;
  const unavailable = mapStateCopy(mapState, block?.mapping_note);
  if (unavailable) {
    return <NoDataState title={unavailable.title} detail={unavailable.detail} />;
  }
  if (error) {
    return <NoDataState title="Map unavailable" detail={error} />;
  }
  if (!features) {
    return <p className="muted">Loading authorised map features…</p>;
  }
  if (features.feature_count === 0) {
    const copy = mapStateCopy(features.map_state === "mapped" ? "no_map_units" : features.map_state, features.mapping_note);
    return <NoDataState title={copy?.title ?? "No map features"} detail={copy?.detail ?? ""} />;
  }

  return (
    <div className="map-panel">
      <MapLibreCanvas
        features={features}
        module={dashboard.module}
        period={period}
        comparison={comparison}
        selectedCode={block.selected_indicator ?? undefined}
      />
      <ul className="map-legend">
        {["green", "yellow", "red", "blue", "missing"].map((status) => (
          <li key={status}>
            <StatusPill status={status} />
          </li>
        ))}
      </ul>
      <p className="muted">
        Coloured by {indicatorName} · {features.feature_count} of{" "}
        {block.map_feature_org_unit_ids.length + block.missing_geometry_ids.length} units mapped · boundaries in force on{" "}
        {block.geometry_effective_date}
        {block.missing_geometry_ids.length ? ` · ${block.missing_geometry_ids.length} without approved geometry` : ""}
        {block.missing_value_ids.length ? ` · ${block.missing_value_ids.length} without a value` : ""}
      </p>
    </div>
  );
}
