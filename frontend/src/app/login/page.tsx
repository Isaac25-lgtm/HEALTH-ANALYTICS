"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { getChildren, getContext, getPreparedDashboard, login, newRequestKey, queryDashboard } from "@/lib/api";
import { clearReadyDashboard, primeDashboard } from "@/lib/dashboard-ready";
import { dashboardHref, DEFAULT_PERIOD } from "@/lib/scope";
import { roleLabel } from "@/components/dashboard/DashboardFrame";
import type { CurrentContext } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [identity, setIdentity] = useState<CurrentContext | null>(null);
  const [stage, setStage] = useState("Signing in…");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (!identity) {
        clearReadyDashboard();
        setStage("Signing in…");
        const result = await login(username, password);
        if ("access_token" in (result as object)) {
          throw new Error("Login response included a forbidden access token.");
        }
        setPassword("");
      }
      const context = await getContext();
      setIdentity(context);
      setStage("Preparing your dashboard…");
      const landing = context.landing_org_unit;
      if (!landing) throw new Error("No authorised landing geography is assigned.");
      const query = { orgUnitId: landing.id, period: DEFAULT_PERIOD, requestKey: newRequestKey() };
      const dashboard = (await getPreparedDashboard(query)) ?? (await queryDashboard(query));
      if (!dashboard.module_result.indicators.some((measure) => measure.raw_value != null)) {
        throw new Error("No governed source-backed indicator values are available for your landing view. An authorised operator must check the live refresh and configuration before you enter.");
      }
      const children = await getChildren(dashboard.scope.id);
      primeDashboard({ context, dashboard, children });
      router.replace(dashboardHref({
        screen: dashboard.screen, orgUnitId: dashboard.scope.id, period: dashboard.period,
        module: dashboard.module, snapshot: dashboard.analysis_snapshot_id,
      }));
    } catch (err) {
      if ((err as Error & { status?: number }).status === 401) setIdentity(null);
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <p className="text-xs uppercase tracking-wide text-navy-mid">Ministry of Health Uganda</p>
      <h1 className="mt-2 text-2xl font-semibold">Health Performance Intelligence</h1>
      <p className="mt-2 text-sm text-slate-600">
        Sign in with a cookie-only session. Tokens are not stored in the browser.
      </p>
      <form onSubmit={onSubmit} className="mt-8 space-y-4 rounded-xl border border-line bg-white p-6">
        {identity ? (
          <div role="status" className="rounded-md border border-line bg-slate-50 p-3 text-sm">
            <p>Signed in as <strong>{identity.display_name}</strong> ({identity.username})</p>
            <p>{roleLabel(identity)} · {identity.landing_org_unit?.name ?? "No assigned geography"}</p>
          </div>
        ) : null}
        {!identity ? <>
        <label className="block text-sm font-medium">
          Username
          <input
            className="mt-1 w-full rounded-md border border-line px-3 py-2"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input
            type="password"
            className="mt-1 w-full rounded-md border border-line px-3 py-2"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        </> : null}
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button type="submit" disabled={busy} className="w-full rounded-md bg-navy px-4 py-2 text-white disabled:opacity-60">
          {busy ? stage : identity ? "Retry dashboard preparation" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
