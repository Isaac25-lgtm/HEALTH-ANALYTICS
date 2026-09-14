import type { CurrentContext, DashboardResponse } from "@/lib/types";

/**
 * Administration workspace. Registries are governed server-side; this surface states what is
 * configured and what still needs an owner decision. It never invents values.
 */
export function AdministrationPanels({
  dashboard,
  context,
}: {
  dashboard: DashboardResponse;
  context: CurrentContext;
}) {
  if (!context.actions.includes("manage_users")) {
    return (
      <section className="card" aria-label="Administration">
        <h2>Administration</h2>
        <p className="banner-info" role="status">
          Your role does not include administration. The server enforces this regardless of navigation.
        </p>
      </section>
    );
  }
  const population = dashboard.population;
  const panels = [
    {
      title: "Populations",
      state: population.status === "unavailable" ? "attention" : "ok",
      detail:
        population.status === "unavailable"
          ? `No approved population for ${dashboard.scope.name}. ${population.reason ?? ""}`
          : `${population.source ?? "Source not stated"} · year ${population.year} · ${population.approval_status}`,
    },
    {
      title: "Geography and boundaries",
      state: dashboard.map.map_state === "mapped" ? "ok" : "attention",
      detail: `Map state: ${dashboard.map.map_state.replaceAll("_", " ")}. Boundary effective date not yet verified.`,
    },
    {
      title: "DHIS2 mappings",
      state: "attention",
      detail: "Host known (hmis.health.go.ug); credentials, metadata mappings and live validation are not configured.",
    },
    {
      title: "AI providers",
      state: "neutral",
      detail: "External AI is disabled for UAT. Deterministic evidence answers remain available.",
    },
    {
      title: "Templates",
      state: "neutral",
      detail: "Official Ministry templates are not supplied; exports use the labelled platform-default family.",
    },
    {
      title: "Programmes you administer",
      state: "ok",
      detail: context.programmes.join(", ") || "None",
    },
  ];
  return (
    <section className="card" aria-label="Administration">
      <h2>Administration</h2>
      <div className="health-grid">
        {panels.map((panel) => (
          <article key={panel.title} className={`health-card health-${panel.state}`}>
            <span className="stat-label">{panel.title}</span>
            <p>{panel.detail}</p>
          </article>
        ))}
      </div>
      <p className="muted">
        Population imports, alias decisions, boundary activation and user provisioning run through audited server
        commands with separation of duties; see docs/DEPLOYMENT.md.
      </p>
    </section>
  );
}
