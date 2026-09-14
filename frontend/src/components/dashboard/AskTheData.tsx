"use client";

import { FormEvent, useState } from "react";
import { askAi } from "@/lib/api";
import type { AiResponse, DashboardResponse } from "@/lib/types";

export function AskTheData({
  dashboard,
  period,
  comparison,
}: {
  dashboard: DashboardResponse;
  period: string;
  comparison?: string;
}) {
  const [question, setQuestion] = useState("Why is this red?");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AiResponse | null>(null);
  const canReport = dashboard.actions.includes("generate_ai_report");

  async function run(task: "findings" | "explain" | "ask" | "report", extra?: { question?: string; indicator_code?: string }) {
    setBusy(task);
    setError(null);
    try {
      const response = await askAi(task, {
        org_unit_id: dashboard.scope.id,
        period,
        module: dashboard.module,
        comparison_period: comparison,
        question: extra?.question,
        indicator_code: extra?.indicator_code ?? dashboard.kpis[0]?.indicator_code ?? undefined,
        analysis_snapshot_id: dashboard.analysis_snapshot_id,
        view_hash: dashboard.view_hash,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The AI request failed.");
    } finally {
      setBusy(null);
    }
  }

  function onAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run("ask", { question });
  }

  const findings = result?.result.findings ?? [];
  const text = result?.result.text;

  return (
    <section className="card ask-panel">
      <h2>Ask the Data</h2>
      <p className="muted">
        Answers use the verified calculation-run evidence only. AI does not calculate official values. When no
        provider is configured, the platform returns a deterministic interpretation.
      </p>
      <div className="export-actions">
        <button type="button" className="export-report" disabled={busy !== null} onClick={() => void run("findings")}>
          {busy === "findings" ? "Working…" : "Key findings"}
        </button>
        <button type="button" className="link-button" disabled={busy !== null} onClick={() => void run("explain")}>
          {busy === "explain" ? "Working…" : "Explain first KPI"}
        </button>
        {canReport ? (
          <button type="button" className="link-button" disabled={busy !== null} onClick={() => void run("report")}>
            {busy === "report" ? "Working…" : "Management brief"}
          </button>
        ) : null}
      </div>
      <form className="filter-bar" onSubmit={onAsk}>
        <label>
          Question
          <input
            aria-label="Ask the Data question"
            value={question}
            maxLength={500}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>
        <button type="submit" className="primary-button" disabled={busy !== null || !question.trim()}>
          {busy === "ask" ? "Working…" : "Ask"}
        </button>
      </form>
      {error ? <p className="banner-info">{error}</p> : null}
      {result ? (
        <div className="ask-result">
          <p className="muted">
            Mode {result.mode}
            {result.fallback_used ? " · deterministic fallback" : ""}
            {result.calculation_run_id ? ` · run ${result.calculation_run_id}` : ""}
            {result.prompt_version ? ` · ${result.prompt_version}` : ""}
          </p>
          {findings.length ? (
            <ul className="alert-list">
              {findings.map((item) => (
                <li key={`${item.title}-${item.indicator_code ?? "none"}`} className="alert alert-info">
                  <strong>{item.title}</strong>
                  <p>{item.detail}</p>
                </li>
              ))}
            </ul>
          ) : null}
          {text ? <p>{text}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
