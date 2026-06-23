import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import {
  fetchDocsStatus,
  fetchHistoryStatus,
  fetchIndexStats,
  fetchIndexStatus,
  startCodeIndex,
  startDocsIndex,
  startHistoryIndex,
  type IndexJob,
} from "../lib/api";

/** Polling interval while an indexing job is running, in milliseconds. */
const POLL_INTERVAL_MS = 1000;

/**
 * Lets the user pick a repository and build the Code Index and (separately) the
 * Git History Index for it, showing live progress and totals for each.
 */
export function IndexPanel() {
  const [path, setPath] = useState<string | null>(null);
  const [codeJob, setCodeJob] = useState<IndexJob | null>(null);
  const [historyJob, setHistoryJob] = useState<IndexJob | null>(null);
  const [docsJob, setDocsJob] = useState<IndexJob | null>(null);
  const [chunks, setChunks] = useState<number | null>(null);
  const [commits, setCommits] = useState<number | null>(null);
  const [docs, setDocs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStats = useCallback(async () => {
    try {
      const stats = await fetchIndexStats();
      setChunks(stats.code_chunks);
      setCommits(stats.commits);
      setDocs(stats.doc_chunks);
    } catch {
      // Sidecar may be starting; StatusPanel surfaces connection issues.
    }
  }, []);

  // On mount: load existing counts and any in-flight job statuses.
  useEffect(() => {
    let cancelled = false;
    void refreshStats();
    fetchIndexStatus().then((j) => !cancelled && setCodeJob(j)).catch(() => undefined);
    fetchHistoryStatus().then((j) => !cancelled && setHistoryJob(j)).catch(() => undefined);
    fetchDocsStatus().then((j) => !cancelled && setDocsJob(j)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [refreshStats]);

  // Poll whichever job is running until it finishes.
  useEffect(() => {
    const codeRunning = codeJob?.state === "running";
    const historyRunning = historyJob?.state === "running";
    const docsRunning = docsJob?.state === "running";
    if (!codeRunning && !historyRunning && !docsRunning) return;

    const timer = window.setInterval(async () => {
      try {
        if (codeRunning) {
          const next = await fetchIndexStatus();
          setCodeJob(next);
          if (next.state !== "running") void refreshStats();
        }
        if (historyRunning) {
          const next = await fetchHistoryStatus();
          setHistoryJob(next);
          if (next.state !== "running") void refreshStats();
        }
        if (docsRunning) {
          const next = await fetchDocsStatus();
          setDocsJob(next);
          if (next.state !== "running") void refreshStats();
        }
      } catch {
        // Ignore transient polling errors; the next tick retries.
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [codeJob?.state, historyJob?.state, docsJob?.state, refreshStats]);

  const busy =
    codeJob?.state === "running" ||
    historyJob?.state === "running" ||
    docsJob?.state === "running";

  const chooseFolder = useCallback(async () => {
    setError(null);
    const selected = await open({
      directory: true,
      multiple: false,
      title: "Choose a repository to index",
    });
    if (typeof selected === "string") setPath(selected);
  }, []);

  const startCode = useCallback(async () => {
    if (!path) return;
    setError(null);
    try {
      setCodeJob(await startCodeIndex(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start indexing");
    }
  }, [path]);

  const startHistory = useCallback(async () => {
    if (!path) return;
    setError(null);
    try {
      setHistoryJob(await startHistoryIndex(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start history indexing");
    }
  }, [path]);

  const startDocs = useCallback(async () => {
    if (!path) return;
    setError(null);
    try {
      setDocsJob(await startDocsIndex(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start docs indexing");
    }
  }, [path]);

  return (
    <section className="index">
      <h2 className="index__title">Index</h2>

      <div className="index__row">
        <button className="index__btn" onClick={chooseFolder} disabled={busy}>
          Choose repository…
        </button>
        <button
          className="index__btn index__btn--primary"
          onClick={startCode}
          disabled={!path || busy}
        >
          {codeJob?.state === "running" ? "Indexing…" : "Index code"}
        </button>
        <button className="index__btn" onClick={startHistory} disabled={!path || busy}>
          {historyJob?.state === "running" ? "Indexing…" : "Index history"}
        </button>
        <button className="index__btn" onClick={startDocs} disabled={!path || busy}>
          {docsJob?.state === "running" ? "Indexing…" : "Index docs"}
        </button>
      </div>

      {path && <p className="index__path" title={path}>{path}</p>}

      <JobProgress label="Code" job={codeJob} />
      <JobProgress label="History" job={historyJob} />
      <JobProgress label="Docs" job={docsJob} />

      {error && <p className="index__error">{error}</p>}

      <p className="index__count">
        {chunks === null ? "—" : `${chunks.toLocaleString()} chunks`}
        {" · "}
        {commits === null ? "—" : `${commits.toLocaleString()} commits`}
        {" · "}
        {docs === null ? "—" : `${docs.toLocaleString()} doc chunks`}
      </p>
    </section>
  );
}

function JobProgress({ label, job }: { label: string; job: IndexJob | null }) {
  if (!job || job.state === "idle") return null;
  const percent = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;
  return (
    <div className="index__progress">
      <div className="index__bar">
        <div className="index__bar-fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="index__status">
        {label}: {statusLabel(job)} {job.total > 0 && `(${job.processed}/${job.total})`}
      </p>
      {job.errors.length > 0 && (
        <ul className="index__errors">
          {job.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function statusLabel(job: IndexJob): string {
  switch (job.state) {
    case "running":
      return job.message ?? "Working…";
    case "done":
      return job.message ?? "Done";
    case "error":
      return `Error: ${job.message ?? "failed"}`;
    default:
      return "";
  }
}
