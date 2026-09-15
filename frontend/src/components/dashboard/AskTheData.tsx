"use client";

import { FormEvent, useState } from "react";
import { askAi } from "@/lib/api";
import type { AiResponse, DashboardResponse } from "@/lib/types";
import { Panel } from "../panels/Panel";

export function AskTheData({
  dashboard,
  period,
  comparison,
  className,
  compact,
}: {
  dashboard: DashboardResponse;
  period: string;
  comparison?: string;
  className?: string;
  compact?: boolean;
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
    <Panel
      icon="ai"
      title="Ask the Data"
      subtitle="Answers from this snapshot's verified evidence only"
      className={`ask-panel ${className ?? ""}`}
    >
      <div className="ask-actions">
        <button type="button" className="secondary-button" disabled={busy !== null} onClick={() => void run("findings")}>
          {busy === "findings" ? "Working…" : "Key findings"}
        </button>
        <button type="button" className="secondary-button" disabled={busy !== null} onClick={() => void run("explain")}>
          {busy === "explain" ? "Working…" : "Explain first KPI"}
        </button>
        {canReport ? (
          <button type="button" className="secondary-button" disabled={busy !== null} onClick={() => void run("report")}>
            {busy === "report" ? "Working…" : "Generate brief"}
          </button>
        ) : null}
      </div>
      <form className="ask-form" onSubmit={onAsk}>
        <input
          aria-label="Ask the Data question"
          value={question}
          maxLength={500}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button type="submit" className="primary-button" disabled={busy !== null || !question.trim()}>
          {busy === "ask" ? "Working…" : "Ask"}
        </button>
      </form>
      {!compact || result || error ? (
        <p className="panel-note">
          AI does not calculate official values. Without a configured provider the platform answers deterministically.
        </p>
      ) : null}
      {error ? <p className="banner-info">{error}</p> : null}
      {result ? (
        <div className="ask-result">
          <p className="panel-note">
            Mode {result.mode}
            {result.fallback_used ? " · deterministic fallback" : ""}
            {result.calculation_run_id ? ` · run ${result.calculation_run_id.slice(0, 8)}` : ""}
          </p>
          {findings.length ? (
            <ul className="insight-list">
              {findings.map((item) => (
                <li key={`${item.title}-${item.indicator_code ?? "none"}`} className="insight insight-info">
                  <div>
                    <p className="insight-title">{item.title}</p>
                    <p className="insight-detail">{item.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
          {text ? <p className="panel-copy">{text}</p> : null}
        </div>
      ) : null}
    </Panel>
  );
}
