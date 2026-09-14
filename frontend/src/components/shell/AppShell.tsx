"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { logout } from "@/lib/api";
import { dashboardHref, MODULE_LABELS, screenForLevel } from "@/lib/scope";
import type { CurrentContext } from "@/lib/types";

const GEO_NAV = [
  { screen: "national", label: "National" },
  { screen: "regional", label: "Regional" },
  { screen: "district", label: "District facilities" },
  { screen: "sub_county", label: "Sub-county facilities" },
  { screen: "facility", label: "Facility" },
];

const WORKSPACE_NAV = [
  { href: "/workspace/anc", label: "ANC/MNCH" },
  { href: "/workspace/intrapartum", label: "Intrapartum and Newborn" },
  { href: "/workspace/immunization", label: "Immunization" },
  { href: "/workspace/mpdsr", label: "MPDSR" },
  { href: "/workspace/maps", label: "Maps" },
  { href: "/workspace/trends", label: "Trends" },
  { href: "/workspace/quality", label: "Data Quality" },
  { href: "/workspace/reports", label: "Reports and Exports" },
  { href: "/workspace/ai", label: "AI Insights" },
];

export function AppShell({
  context,
  screen,
  children,
}: {
  context: CurrentContext;
  screen: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const landing = context.landing_org_unit;
  const navUnit = (target: string) =>
    [...context.landing_org_units, ...context.geography_scopes].find(
      (unit) => screenForLevel(unit.level_type) === target,
    ) ?? landing;

  async function onLogout() {
    await logout();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <p className="eyebrow">Ministry of Health Uganda</p>
          <p className="brand-title">Health Performance Intelligence</p>
        </div>
        <nav aria-label="Geography screens">
          {GEO_NAV.map((item) => (
            <Link
              key={item.screen}
              className={item.screen === screen ? "nav-item active" : "nav-item"}
              href={dashboardHref({
                screen: item.screen,
                orgUnitId: navUnit(item.screen)?.id,
              })}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <nav aria-label="Programme workspaces">
          {WORKSPACE_NAV.map((item) => (
            <Link key={item.href} className="nav-item" href={item.href}>
              {item.label}
            </Link>
          ))}
          {context.actions.includes("manage_users") ? (
            <Link className="nav-item" href="/workspace/admin">
              Administration
            </Link>
          ) : null}
        </nav>
        <p className="sidebar-note">
          Authorised programmes: {context.programmes.map((code) => MODULE_LABELS[code.toLowerCase()] ?? code).join(", ") || "None"}
        </p>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <h1>Uganda Health Performance Intelligence</h1>
            <p className="muted">
              {context.display_name} · {landing ? `${landing.name} (${landing.level_type})` : "No landing geography"}
            </p>
          </div>
          <button type="button" className="ghost-button" onClick={onLogout}>
            Sign out
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
