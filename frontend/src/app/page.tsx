"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getContext } from "@/lib/api";
import { dashboardHref, screenForLevel } from "@/lib/scope";
import { LoadingState } from "@/components/ui/EmptyStates";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    getContext()
      .then((context) => {
        const landing = context.landing_org_unit;
        router.replace(
          dashboardHref({
            screen: screenForLevel(landing?.level_type),
            orgUnitId: landing?.id,
          }),
        );
      })
      .catch((err: Error & { status?: number }) => {
        if (err.status === 401) {
          router.replace("/login");
        }
      });
  }, [router]);

  return <LoadingState label="Opening your authorised dashboard…" />;
}
