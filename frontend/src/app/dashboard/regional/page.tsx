"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { LoadingState } from "@/components/ui/EmptyStates";

function Screen() {
  const params = useSearchParams();
  return (
    <DashboardView
      screen="regional"
      orgUnitId={params.get("orgUnitId") ?? undefined}
      period={params.get("period") ?? undefined}
      comparison={params.get("comparison") ?? undefined}
      module={params.get("module") ?? undefined}
      indicator={params.get("indicator") ?? undefined}
      request={params.get("request") ?? undefined}
      snapshot={params.get("snapshot") ?? undefined}
    />
  );
}

export default function RegionalDashboardPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Screen />
    </Suspense>
  );
}
