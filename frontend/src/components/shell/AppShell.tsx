"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { logout } from "@/lib/api";
import { dashboardHref, MODULE_LABELS, screenForLevel } from "@/lib/scope";
import type { CurrentContext, DashboardResponse } from "@/lib/types";
import { WORKSPACES } from "@/lib/workspaces";
import { roleLabel } from "../dashboard/DashboardFrame";
import { Icon, type IconName } from "../ui/Icon";

const GEO_NAV: Array<{ screen: string; label: string; icon: IconName }> = [
  { screen: "national", label: "National", icon: "national" },
  { screen: "regional", label: "Regional", icon: "regional" },
  { screen: "district", label: "District facilities", icon: "district" },
  { screen: "sub_county", label: "Sub-county facilities", icon: "sub_county" },
  { screen: "facility", label: "Facility", icon: "facility" },
];

const WORKSPACE_ICONS: Record<string, IconName> = {
  anc: "anc",
  intrapartum: "intrapartum",
  immunization: "immunization",
  mpdsr: "mpdsr",
  maps: "maps",
  trends: "trends",
  quality: "quality",
  reports: "reports",
  ai: "ai",
  admin: "admin",
};

const WORKSPACE_NAV = Object.values(WORKSPACES)
  .filter((item) => item.slug !== "admin")
  .map((item) => ({ slug: item.slug, href: `/workspace/${item.slug}`, label: item.label, icon: WORKSPACE_ICONS[item.slug] }));

const PROGRAMME_WORKSPACE: Record<string, string> = {
  anc: "MNCH",
  intrapartum: "MNCH",
  immunization: "EPI",
  mpdsr: "MPDSR",
};

export type ShellAlerts = { count: number; href: string };

export function AppShell({
  context,
  dashboard,
  screen,
  workspace,
  subtitle,
  alerts,
  children,
}: {
  context: CurrentContext;
  dashboard: DashboardResponse;
  screen: string;
  workspace?: string;
  subtitle?: string;
  alerts?: ShellAlerts;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const landing = context.landing_org_unit;
  const role = roleLabel(context);
  const navCandidates = [dashboard.scope, ...dashboard.ancestors, ...context.geography_entry_units];
  const navUnit = (target: string) =>
    navCandidates.find(
      (unit) => screenForLevel(unit.level_type) === target,
    );
  const visibleWorkspaces = WORKSPACE_NAV.filter((item) => {
    const programme = PROGRAMME_WORKSPACE[item.slug];
    if (programme) {
      return context.actions.includes("view") && context.programmes.includes(programme);
    }
    if (item.slug === "reports") return context.actions.includes("export");
    if (item.slug === "ai") return context.actions.includes("generate_ai_report");
    return context.actions.includes("view");
  });
  const linkState = {
    orgUnitId: dashboard.scope.id,
    period: dashboard.period,
    comparison: dashboard.comparison_period,
  };

  async function onLogout() {
    await logout();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to dashboard
      </a>
      <aside className="sidebar">
        <div className="brand">
          {/* No official crest is extracted or invented; the slot is reserved for an approved asset. */}
          <div className="brand-slot" role="img" aria-label="Reserved for the approved Ministry of Health crest">
            <span aria-hidden="true">Crest</span>
          </div>
          <div>
            <p className="brand-title">Ministry of Health</p>
            <p className="brand-subtitle">Republic of Uganda</p>
          </div>
        </div>
        <nav aria-label="Geography screens" className="nav-group">
          {GEO_NAV.filter((item) => navUnit(item.screen)).map((item) => {
            const current = !workspace && item.screen === screen;
            const unit = navUnit(item.screen);
            return (
              <Link
                key={item.screen}
                className={current ? "nav-item active" : "nav-item"}
                aria-current={current ? "page" : undefined}
                href={dashboardHref({
                  ...linkState,
                  screen: item.screen,
                  orgUnitId: unit?.id,
                  module: dashboard.module,
                })}
              >
                <Icon name={item.icon} size={20} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <nav aria-label="Programme workspaces" className="nav-group">
          {visibleWorkspaces.map((item) => {
            const current = workspace === item.slug;
            const pinnedModule = WORKSPACES[item.slug]?.module;
            return (
              <Link
                key={item.href}
                className={current ? "nav-item active" : "nav-item"}
                aria-current={current ? "page" : undefined}
                href={dashboardHref({
                  ...linkState,
                  workspace: item.slug,
                  module: pinnedModule ?? dashboard.module,
                })}
              >
                <Icon name={item.icon} size={20} />
                <span>{item.label}</span>
              </Link>
            );
          })}
          {context.actions.includes("manage_users") ? (
            <Link
              className={workspace === "admin" ? "nav-item active" : "nav-item"}
              aria-current={workspace === "admin" ? "page" : undefined}
              href={dashboardHref({ ...linkState, workspace: "admin", module: dashboard.module })}
            >
              <Icon name="admin" size={20} />
              <span>Administration</span>
            </Link>
          ) : null}
        </nav>
        <div className="sidebar-foot">
          <p className="sidebar-note">
            Authorised programmes:{" "}
            {context.programmes.map((code) => MODULE_LABELS[code.toLowerCase()] ?? code).join(", ") || "None"}
          </p>
          <p className="sidebar-tagline">Health Performance Intelligence</p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="topbar-titles">
            <h1>Health Performance Intelligence</h1>
            <p className="topbar-subtitle">{subtitle ?? (landing ? landing.name : "No landing geography")}</p>
          </div>
          <div className="topbar-user">
            {alerts ? (
              <Link
                href={alerts.href}
                className="topbar-alerts"
                aria-label={`Data-quality alerts: ${alerts.count} open flag${alerts.count === 1 ? "" : "s"}`}
              >
                <Icon name="bell" size={22} />
                {alerts.count ? <span className="alert-badge">{alerts.count > 99 ? "99+" : alerts.count}</span> : null}
              </Link>
            ) : null}
            <span className="user-avatar" aria-hidden="true">
              {(context.display_name || context.username).slice(0, 1).toUpperCase()}
            </span>
            <span className="user-names">
              <strong>{context.display_name}</strong>
              {role !== context.display_name ? <span>{role}</span> : null}
            </span>
            <button type="button" className="ghost-button signout-button" onClick={onLogout}>
              <Icon name="logout" size={16} />
              <span>Sign out</span>
            </button>
            <p className="topbar-tagline" aria-label="Platform note">
              Deterministic, permission-scoped
              <br />
              analytics from committed snapshots
            </p>
          </div>
        </header>
        <main id="main-content" className="workspace-main">
          {children}
        </main>
      </div>
    </div>
  );
}
