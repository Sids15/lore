import { useCallback, useEffect, useState } from "react";

import { fetchEvalStatus, runEval, type EvalJob, type EvalReport } from "../lib/api";

const POLL_INTERVAL_MS = 1000;

const EXAMPLE_EVAL = `# .lore/eval.yml
questions:
  - q: "Where is the retry logic implemented?"
    relevant: ["sidecar/app/llm/ollama_client.py"]
  - q: "What calls build_digraph?"
    relevant: ["sidecar/app/graph/analysis.py"]`;

/**
 * Runs the local evaluation harness over the repo's golden question set and
 * shows the quality metrics (retrieval recall, faithfulness, answer relevancy)
 * plus a per-question breakdown.
 */
export function EvalPanel() {
  const [job, setJob] = useState<EvalJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchEvalStatus().then((j) => !cancelled && setJob(j)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        setJob(await fetchEvalStatus());
      } catch {
        // Ignore transient polling errors; the next tick retries.
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [job?.state]);

  const run = useCallback(async () => {
    setError(null);
    try {
      setJob(await runEval());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start evaluation");
    }
  }, []);

  const running = job?.state === "running";

  return (
    <section className="eval">
      <div className="eval__head">
        <h2 className="eval__title">Evaluation</h2>
        <button className="index__btn index__btn--primary" onClick={() => void run()} disabled={running}>
          {running ? "Running…" : "Run evaluation"}
        </button>
      </div>

      {running && (
        <p className="index__status">
          Evaluating… ({job.processed}/{job.total})
        </p>
      )}

      {error && <p className="eval__error">{error}</p>}

      {job?.state === "error" && <p className="eval__error">{job.message}</p>}

      {job?.state === "done" && !job.configured && (
        <div className="eval__empty">
          <p className="placeholder">
            No <code>.lore/eval.yml</code> found in the repo. Add a golden question set, then
            run again:
          </p>
          <pre className="graph__example">{EXAMPLE_EVAL}</pre>
        </div>
      )}

      {job?.report && <Report report={job.report} />}
    </section>
  );
}

function Report({ report }: { report: EvalReport }) {
  return (
    <>
      <div className="eval__metrics">
        <Metric label="Faithfulness" value={pct(report.faithfulness)} />
        <Metric
          label="Recall@k"
          value={report.recall_at_k === null ? "n/a" : pct(report.recall_at_k)}
        />
        <Metric label="Answer relevancy" value={pct(report.answer_relevancy)} />
      </div>

      <table className="eval__table">
        <thead>
          <tr>
            <th>Question</th>
            <th>Grounded</th>
            <th>Recall</th>
            <th>Relevancy</th>
          </tr>
        </thead>
        <tbody>
          {report.per_question.map((r, i) => (
            <tr key={i}>
              <td>{r.question}</td>
              <td>{r.grounded ? "yes" : "no"}</td>
              <td>{r.recall_hit === null ? "—" : r.recall_hit ? "hit" : "miss"}</td>
              <td>{r.relevancy.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="eval__metric">
      <span className="eval__metric-value">{value}</span>
      <span className="eval__metric-label">{label}</span>
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
