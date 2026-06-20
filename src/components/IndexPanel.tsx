import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import {
  fetchIndexStats,
  fetchIndexStatus,
  startCodeIndex,
  type IndexJob,
} from "../lib/api";

/** Polling interval while an indexing job is running, in milliseconds. */
const POLL_INTERVAL_MS = 1000;

/**
 * Lets the user pick a repository with the native folder dialog and build the
 * Code Index for it, showing live progress and the total indexed chunk count.
 */
export function IndexPanel() {
  const [path, setPath] = useState<string | null>(null);
  const [job, setJob] = useState<IndexJob | null>(null);
  const [chunks, setChunks] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStats = useCallback(async () => {
    try {
      const stats = await fetchIndexStats();
      setChunks(stats.code_chunks);
    } catch {
      // Sidecar may be starting; the StatusPanel surfaces connection issues.
    }
  }, []);

  // On mount: load current job status and the existing chunk count.
  useEffect(() => {
    let cancelled = false;
    void refreshStats();
    fetchIndexStatus()
      .then((j) => {
        if (!cancelled) setJob(j);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [refreshStats]);

  // While a job is running, poll its status until it finishes.
  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await fetchIndexStatus();
        setJob(next);
        if (next.state !== "running") void refreshStats();
      } catch {
        // Ignore transient polling errors; the next tick retries.
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [job?.state, refreshStats]);

  const chooseFolder = useCallback(async () => {
    setError(null);
    const selected = await open({
      directory: true,
      multiple: false,
      title: "Choose a repository to index",
    });
    if (typeof selected === "string") setPath(selected);
  }, []);

  const startIndexing = useCallback(async () => {
    if (!path) return;
    setError(null);
    try {
      setJob(await startCodeIndex(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start indexing");
    }
  }, [path]);

  const running = job?.state === "running";
  const percent =
    job && job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;

  return (
    <section className="index">
      <h2 className="index__title">Code Index</h2>

      <div className="index__row">
        <button className="index__btn" onClick={chooseFolder} disabled={running}>
          Choose repository…
        </button>
        <button
          className="index__btn index__btn--primary"
          onClick={startIndexing}
          disabled={!path || running}
        >
          {running ? "Indexing…" : "Index"}
        </button>
      </div>

      {path && <p className="index__path" title={path}>{path}</p>}

      {job && job.state !== "idle" && (
        <div className="index__progress">
          <div className="index__bar">
            <div className="index__bar-fill" style={{ width: `${percent}%` }} />
          </div>
          <p className="index__status">
            {labelFor(job)} {job.total > 0 && `(${job.processed}/${job.total})`}
          </p>
        </div>
      )}

      {job?.errors?.length ? (
        <ul className="index__errors">
          {job.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      ) : null}

      {error && <p className="index__error">{error}</p>}

      <p className="index__count">
        {chunks === null ? "—" : `${chunks.toLocaleString()} chunks indexed`}
      </p>
    </section>
  );
}

function labelFor(job: IndexJob): string {
  switch (job.state) {
    case "running":
      return job.message ?? "Indexing…";
    case "done":
      return job.message ?? "Done";
    case "error":
      return `Error: ${job.message ?? "indexing failed"}`;
    default:
      return "";
  }
}
