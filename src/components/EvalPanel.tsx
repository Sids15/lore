import { useCallback, useEffect, useState } from "react";

import { fetchEvalStatus, runEval, type EvalJob, type EvalReport } from "../lib/api";

const POLL_INTERVAL_MS = 1000;

const EXAMPLE_EVAL = `# .lore/eval.yml
questions:
  - q: "Where is the retry logic implemented?"
    relevant: ["sidecar/app/llm/ollama_client.py"]
  - q: "What calls build_digraph?"
    relevant: ["sidecar/app/graph/analysis.py"]`;

const DEFS = [
  { title: "Faithfulness", text: "Share of answers fully supported by their cited sources." },
  { title: "Recall@k", text: "How often the relevant files appear in what was retrieved." },
  { title: "Answer relevancy", text: "How well each answer addresses the question asked." },
];

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
        /* transient */
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
  const idle =
    !running && !job?.report && job?.state !== "error" && !(job?.state === "done" && !job.configured);

  return (
    <section className="ws">
      <header className="ws__head">
        <div>
          <h2 className="ws__title">Eval</h2>
          <p className="ws__sub">
            Measure answer quality against a held-out question set — locally, with no labels leaving
            the machine.
          </p>
        </div>
        <button className="btn btn--primary" onClick={() => void run()} disabled={running}>
          {running ? "Running…" : job?.report ? "Re-run" : "Run evaluation"}
        </button>
      </header>

      <div className="ws__body">
        {error && <p className="ev__error">{error}</p>}
        {job?.state === "error" && <p className="ev__error">{job.message}</p>}

        {running && (
          <div className="ev__running">
            <div className="spinner" aria-hidden />
            <div>Running evaluation…</div>
            <div className="ev__caption">scoring {job.processed} / {job.total || "?"}</div>
            <div className="progress">
              <i style={{ width: `${job.total ? Math.round((job.processed / job.total) * 100) : 10}%` }} />
            </div>
          </div>
        )}

        {idle && (
          <div className="empty">
            <BarGlyph />
            <h2 className="empty__title">No evaluation run yet</h2>
            <p className="empty__text">
              Lore replays your question set against the current index and scores every answer on
              three axes. A full run takes about a minute.
            </p>
            <div className="ev__defs">
              {DEFS.map((d) => (
                <div key={d.title} className="ev__def">
                  <div className="ev__def-title">{d.title}</div>
                  <div className="ev__def-text">{d.text}</div>
                </div>
              ))}
            </div>
            <p className="ev__caption">runs against <code>.lore/eval.yml</code> · llama3.1:8b</p>
          </div>
        )}

        {job?.state === "done" && !job.configured && (
          <div className="empty">
            <BarGlyph />
            <h2 className="empty__title">No question set yet</h2>
            <p className="empty__text">
              Add a <code>.lore/eval.yml</code> with a few questions and their relevant files, then
              run again:
            </p>
            <pre className="graph__example" style={{ textAlign: "left", maxWidth: "100%" }}>{EXAMPLE_EVAL}</pre>
          </div>
        )}

        {job?.report && <Report report={job.report} />}
      </div>
    </section>
  );
}

function Report({ report }: { report: EvalReport }) {
  return (
    <>
      <div className="ev__metrics">
        <Metric name="Faithfulness" value={report.faithfulness} good={0.85} />
        <Metric name="Recall@k" value={report.recall_at_k} good={0.8} />
        <Metric name="Answer relevancy" value={report.answer_relevancy} good={0.85} />
      </div>

      <div className="ev__panel">
        <div className="ev__panel-head">
          <span className="ev__panel-title">Per-question results</span>
          <span className="ev__panel-count">{report.total} questions</span>
        </div>
        <div className="ev__row ev__row--head">
          <span>Question</span>
          <span>Grounded</span>
          <span>Recall</span>
          <span>Relevancy</span>
          <span />
        </div>
        {report.per_question.map((r, i) => (
          <div key={i} className="ev__row">
            <span className="ev__q" title={r.question}>{r.question}</span>
            <span className={`ev__score ${r.grounded ? "ev__score--good" : "ev__score--warn"}`}>
              {r.grounded ? "yes" : "no"}
            </span>
            <span className="ev__cell">
              {r.recall_hit === null ? "—" : r.recall_hit ? "hit" : "miss"}
            </span>
            <span className={`ev__score ${r.relevancy >= 0.85 ? "ev__score--good" : "ev__score--warn"}`}>
              {r.relevancy.toFixed(2)}
            </span>
            <span />
          </div>
        ))}
      </div>
    </>
  );
}

function Metric({ name, value, good }: { name: string; value: number | null; good: number }) {
  const ok = value !== null && value >= good;
  const pct = value === null ? 0 : Math.round(value * 100);
  return (
    <div className="ev__metric">
      <div className="ev__metric-head">
        <span className="ev__metric-name">{name}</span>
      </div>
      <span className={`ev__metric-num ${ok ? "" : "ev__metric-num--warn"}`}>
        {value === null ? "n/a" : value.toFixed(2)}
      </span>
      <div className={`ev__metric-bar ${ok ? "" : "ev__metric-bar--warn"}`}>
        <i style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function BarGlyph() {
  return (
    <div className="empty__tile">
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
        <rect x="3" y="13" width="3.4" height="7" rx="1.2" fill="currentColor" opacity="0.5" />
        <rect x="8.3" y="9" width="3.4" height="11" rx="1.2" fill="currentColor" opacity="0.5" />
        <rect x="13.6" y="11" width="3.4" height="9" rx="1.2" fill="currentColor" opacity="0.5" />
        <rect x="18.9" y="6" width="3.4" height="14" rx="1.2" fill="currentColor" />
      </svg>
    </div>
  );
}
