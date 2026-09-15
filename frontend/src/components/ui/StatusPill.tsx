import { statusMeta } from "@/lib/status";

export function StatusPill({ status }: { status: string }) {
  const meta = statusMeta(status);
  return (
    <span className={`status-pill ${meta.className}`} title={meta.label}>
      <span className="status-dot" aria-hidden="true" />
      <span>{meta.label}</span>
    </span>
  );
}
