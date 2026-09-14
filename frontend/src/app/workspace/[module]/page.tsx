"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { LoadingState } from "@/components/ui/EmptyStates";

const MODULE_BY_SLUG: Record<string, string | undefined> = {
  anc: "anc",
  intrapartum: "intrapartum",
  immunization: "immunization",
  mpdsr: "mpdsr",
  maps: undefined,
  trends: undefined,
  quality: undefined,
  reports: undefined,
  ai: undefined,
  admin: undefined,
};

function Screen() {
  const params = useParams<{ module: string }>();
  const search = useSearchParams();
  const programmeModule = MODULE_BY_SLUG[params.module];
  return (
    <DashboardView
      screen="national"
      orgUnitId={search.get("orgUnitId") ?? undefined}
      period={search.get("period") ?? undefined}
      comparison={search.get("comparison") ?? undefined}
      module={programmeModule ?? search.get("module") ?? undefined}
      indicator={search.get("indicator") ?? undefined}
      request={search.get("request") ?? undefined}
      snapshot={search.get("snapshot") ?? undefined}
      workspace={params.module}
    />
  );
}

export default function WorkspacePage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Screen />
    </Suspense>
  );
}
