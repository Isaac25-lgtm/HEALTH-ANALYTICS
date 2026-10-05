"use client";

import { useEffect, useRef, useState } from "react";
import { getFacilityStatus } from "@/lib/api";
import type { DashboardResponse, FacilityData } from "@/lib/types";
import { Icon } from "../ui/Icon";

const POLL_MS = 5000;
const MAX_POLLS = 120;

/**
 * D-068: facility figures load from DHIS2 when a district is first opened. While they load the
 * screen says so, polls the server, and re-runs the dashboard once they are stored. Nothing is
 * shown as zero in the meantime.
 */
export function FacilityDataBanner({
  dashboard,
  onReady,
}: {
  dashboard: DashboardResponse;
  onReady: () => void;
}) {
  const [state, setState] = useState<FacilityData | null | undefined>(dashboard.facility_data);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    setState(dashboard.facility_data);
    if (dashboard.facility_data?.status !== "loading") {
      return;
    }
    let cancelled = false;
    let polls = 0;
    let inFlight = false;
    const timer = window.setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      polls += 1;
      try {
        const next = await getFacilityStatus(dashboard.scope.id, dashboard.period, dashboard.module);
        if (cancelled) {
          return;
        }
        if (next.status === "ready") {
          window.clearInterval(timer);
          // Keep the notice until the re-run dashboard replaces this one.
          setState({ ...next, status: "loading", message: "Facility data stored. Updating the screen…" });
          readyRef.current();
          return;
        }
        setState(polls >= MAX_POLLS && next.status === "loading"
          ? { ...next, status: "unavailable", message: "Facility data is still being prepared. Refresh this view later; missing figures are not zero." }
          : next);
        if (next.status !== "loading" || polls >= MAX_POLLS) {
          window.clearInterval(timer);
        }
      } catch {
        if (polls >= MAX_POLLS) {
          window.clearInterval(timer);
          if (!cancelled) setState({ status: "unavailable", job_id: null, months_requested: 0, months_loaded: 0, message: "The facility status could not be confirmed. Refresh the view to retry." });
        }
      } finally {
        inFlight = false;
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [dashboard]);

  if (!state || state.status === "ready" || state.status === "not_applicable") {
    return null;
  }
  const loading = state.status === "loading";
  return (
    <p className={`facility-banner facility-${state.status}`} role="status" aria-live="polite">
      <Icon name={loading ? "download" : "alert"} size={16} />
      <span>
        {loading ? state.message ?? "Loading facility data from DHIS2…" : state.message ?? "Facility data is not available."}
        {loading && state.months_requested && state.months_loaded < state.months_requested
          ? ` ${state.months_loaded} of ${state.months_requested} months already stored; this can take a minute.`
          : ""}
      </span>
    </p>
  );
}
