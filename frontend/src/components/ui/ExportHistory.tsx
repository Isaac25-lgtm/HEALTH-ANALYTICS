"use client";

import { useEffect, useState } from "react";
import { downloadExportFile, listExportJobs, retryExportJob } from "@/lib/api";
import type { ExportJobSummary } from "@/lib/types";
import { Panel } from "../panels/Panel";

/**
 * The caller's own export jobs. Every field shown here comes from the server: status,
 * retryability and expiry are decided there, not inferred in the browser.
 */
export function ExportHistory({ className }: { className?: string }) {
  const [jobs, setJobs] = useState<ExportJobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    try {
      const result = await listExportJobs();
      setJobs(result.jobs);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export history is unavailable.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <Panel
      icon="reports"
      title="Recent export jobs"
      subtitle="Your own jobs; status and expiry come from the server"
      className={className}
      actions={
        <button type="button" className="link-button" onClick={() => void refresh()}>
          Refresh
        </button>
      }
    >
      {error ? <p className="banner-info">{error}</p> : null}
      {jobs === null ? (
        <p className="muted">Loading job history…</p>
      ) : jobs.length === 0 ? (
        <p className="muted">No export has been requested from this account yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="sr-only">Export jobs for the signed-in user</caption>
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Period</th>
                <th scope="col">Status</th>
                <th scope="col">Attempts</th>
                <th scope="col">Requested</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id}>
                  <td>{job.label}</td>
                  <td>
                    {job.period}
                    {job.module ? ` · ${job.module}` : ""}
                  </td>
                  <td>
                    <span className={`chip chip-${job.status}`}>{job.status}</span>
                    {job.artifact_expired ? <span className="chip chip-expired">file expired</span> : null}
                    {job.error_message ? <p className="muted">{job.error_message}</p> : null}
                  </td>
                  <td className="num">
                    {job.attempt_count}
                    {job.max_attempts ? ` / ${job.max_attempts}` : ""}
                  </td>
                  <td>{job.created_at ? new Date(job.created_at).toLocaleString() : "—"}</td>
                  <td>
                    {job.downloadable ? (
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy === job.job_id}
                        onClick={async () => {
                          setBusy(job.job_id);
                          try {
                            await downloadExportFile(job.job_id);
                          } catch (err) {
                            setError(err instanceof Error ? err.message : "Download failed.");
                          } finally {
                            setBusy(null);
                          }
                        }}
                      >
                        Download
                      </button>
                    ) : job.retryable ? (
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy === job.job_id}
                        onClick={async () => {
                          setBusy(job.job_id);
                          try {
                            await retryExportJob(job.job_id);
                            await refresh();
                          } catch (err) {
                            setError(err instanceof Error ? err.message : "Retry was refused.");
                          } finally {
                            setBusy(null);
                          }
                        }}
                      >
                        Retry
                      </button>
                    ) : (
                      <span className="muted">
                        {job.artifact_expired ? "Request it again" : job.permanent_failure ? "Not retryable" : "—"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="panel-note">
        Generated files are kept for a limited retention window; the job record and its checksum outlive the file, so an
        expired download is explained rather than silently missing.
      </p>
    </Panel>
  );
}
