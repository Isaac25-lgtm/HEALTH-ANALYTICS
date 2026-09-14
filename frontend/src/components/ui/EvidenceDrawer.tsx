import { formatMeasure } from "@/lib/status";
import type { Measure } from "@/lib/types";

export function EvidenceDrawer({
  measure,
  onClose,
}: {
  measure: Measure | null;
  onClose: () => void;
}) {
  if (!measure) {
    return null;
  }
  return (
    <aside className="drawer" role="dialog" aria-label="Evidence and methodology">
      <div className="drawer-head">
        <h2>{measure.name ?? measure.indicator_code}</h2>
        <button type="button" className="link-button" onClick={onClose}>
          Close
        </button>
      </div>
      <dl className="meta-list">
        <div>
          <dt>Value</dt>
          <dd>{formatMeasure(measure.raw_value, measure.unit, measure.display_value)}</dd>
        </div>
        <div>
          <dt>Numerator</dt>
          <dd className="num">{measure.numerator ?? "Missing"}</dd>
        </div>
        <div>
          <dt>Denominator</dt>
          <dd className="num">{measure.denominator ?? "Missing"}</dd>
        </div>
        <div>
          <dt>Unit</dt>
          <dd>{measure.unit ?? "—"}</dd>
        </div>
        <div>
          <dt>Formula version</dt>
          <dd>{measure.formula_version ?? "—"}</dd>
        </div>
        <div>
          <dt>Mapping version</dt>
          <dd>{measure.mapping_version ?? "—"}</dd>
        </div>
        <div>
          <dt>Calculation run</dt>
          <dd>{measure.calculation_run_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Population year</dt>
          <dd>{measure.population_year ?? "Not used"}</dd>
        </div>
        <div>
          <dt>Aggregation</dt>
          <dd>{measure.aggregation_policy ?? "—"}</dd>
        </div>
        <div>
          <dt>Population version</dt>
          <dd>{measure.population_version_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Facility population entry</dt>
          <dd>{measure.facility_population_entry_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Denominator type</dt>
          <dd>{measure.denominator_type ?? "—"}</dd>
        </div>
      </dl>
      {measure.blue_reason ? <p className="banner-info">{measure.blue_reason}</p> : null}
      {measure.missing_components?.length ? (
        <p className="muted">Missing components: {measure.missing_components.join(", ")}</p>
      ) : null}
    </aside>
  );
}
