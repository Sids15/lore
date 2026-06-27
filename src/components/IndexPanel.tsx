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
export function IndexPanel({
  path,
  setPath,
}: {
  path: string | null;
  setPath: (path: string | null) => void;
}) {
  const [codeJob, setCodeJob] = useState<IndexJob | null>(null);
  const [historyJob, setHistoryJob] = useState<IndexJob | null>(null);
  const [docsJob, setDocsJob] = useState<IndexJob | null>(null);
  const [chunks, setChunks] = useState<number | null>(null);
  const [commits, setCommits] = useState<number | null>(null);
  const [docs, setDocs] = useState<number | null>(null);
  const [force, setForce] = useState(false);
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
      setCodeJob(await startCodeIndex(path, force));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start indexing");
    }
  }, [path, force]);

  const startHistory = useCallback(async () => {
    if (!path) return;
    setError(null);
    try {
      setHistoryJob(await startHistoryIndex(path, force));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start history indexing");
    }
  }, [path, force]);

  const startDocs = useCallback(async () => {
    if (!path) return;
    setError(null);
    try {
      setDocsJob(await startDocsIndex(path, force));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start docs indexing");
    }
  }, [path, force]);

  return (
    <section className="ws">
      <header className="ws__head">
        <div>
          <h2 className="ws__title">Index</h2>
          <p className="ws__sub">
            Point Lore at a repository and build its three indexes. Re-indexing is incremental.
          </p>
        </div>
        <button className="btn" onClick={chooseFolder} disabled={busy}>Choose repository…</button>
      </header>

      <div className="ws__body">
        {!path ? (
          <div className="empty">
            <div className="empty__tile"><FolderIcon /></div>
            <h2 className="empty__title">Choose a repository to begin</h2>
            <p className="empty__text">
              Pick a local repo, then build its code, history, and docs indexes so you can ask
              grounded questions about it.
            </p>
          </div>
        ) : (
          <>
            <div className="idx__repo">
              <div className="idx__repo-tile"><FolderIcon /></div>
              <div>
                <div className="idx__repo-path">{path}</div>
                <div className="idx__repo-meta">{busy ? "indexing…" : "ready to index"}</div>
              </div>
              <label className="switch idx__repo-force">
                <span>Force full re-index</span>
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(e) => setForce(e.currentTarget.checked)}
                  disabled={busy}
                />
                <span className="switch__track"><span className="switch__knob" /></span>
              </label>
            </div>

            <div className="idx__grid">
              <IndexCard kind="code" title="Code" sub="AST-aware chunks" job={codeJob} onRun={startCode} busy={busy} />
              <IndexCard kind="history" title="History" sub="commit summaries" job={historyJob} onRun={startHistory} busy={busy} />
              <IndexCard kind="docs" title="Docs" sub="markdown + text" job={docsJob} onRun={startDocs} busy={busy} />
            </div>

            <div className="idx__agg">
              <AggCell num={chunks} label="chunks" />
              <AggCell num={commits} label="commits" />
              <AggCell num={docs} label="docs" />
            </div>
          </>
        )}

        {error && <p className="idx__error">{error}</p>}
      </div>
    </section>
  );
}

type IdxKind = "code" | "history" | "docs";

function IndexCard({
  kind,
  title,
  sub,
  job,
  onRun,
  busy,
}: {
  kind: IdxKind;
  title: string;
  sub: string;
  job: IndexJob | null;
  onRun: () => void;
  busy: boolean;
}) {
  const running = job?.state === "running";
  const pct = job
    ? job.total > 0
      ? Math.round((job.processed / job.total) * 100)
      : job.state === "done"
        ? 100
        : 0
    : 0;
  const status =
    !job || job.state === "idle"
      ? "not indexed"
      : running
        ? "indexing…"
        : job.state === "done"
          ? "up to date"
          : "failed";
  const counts = job?.state === "done" ? parseCounts(job.message) : null;

  return (
    <div className="idxc">
      <div className="idxc__head">
        <div className={`idxc__tile idxc__tile--${kind}`}><KindIcon kind={kind} /></div>
        <div>
          <div className="idxc__title">{title}</div>
          <div className="idxc__sub">{sub}</div>
        </div>
      </div>

      <div className="idxc__track">
        <div className={`idxc__fill idxc__fill--${kind}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="idxc__statusline">
        <span>{status}</span>
        <span>{running ? `${pct}%` : ""}</span>
      </div>

      {counts && (
        <div className="idxc__pills">
          <div className="idxc__pill idxc__pill--changed">
            <span className="idxc__pill-num">{counts.changed}</span>
            <span className="idxc__pill-label">changed</span>
          </div>
          <div className="idxc__pill">
            <span className="idxc__pill-num">{counts.unchanged}</span>
            <span className="idxc__pill-label">unchanged</span>
          </div>
          <div className="idxc__pill idxc__pill--removed">
            <span className="idxc__pill-num">{counts.removed}</span>
            <span className="idxc__pill-label">removed</span>
          </div>
        </div>
      )}

      <button className="btn btn--primary" onClick={onRun} disabled={busy} style={{ justifyContent: "center" }}>
        {running ? "Indexing…" : job?.state === "done" ? "Re-index" : "Build index"}
      </button>
    </div>
  );
}

function AggCell({ num, label }: { num: number | null; label: string }) {
  return (
    <div className="idx__agg-cell">
      <span className="idx__agg-num">{num === null ? "—" : num.toLocaleString()}</span>
      <span className="idx__agg-label">{label}</span>
    </div>
  );
}

/** Best-effort parse of "N changed, M unchanged, K removed" (or "N new") from a job message. */
function parseCounts(message: string | null): { changed: string; unchanged: string; removed: string } | null {
  if (!message) return null;
  const changed = /(\d+)\s+changed/.exec(message) ?? /(\d+)\s+new/.exec(message);
  const unchanged = /(\d+)\s+unchanged/.exec(message);
  const removed = /(\d+)\s+removed/.exec(message);
  if (!changed && !unchanged) return null;
  return {
    changed: changed ? changed[1] : "0",
    unchanged: unchanged ? unchanged[1] : "0",
    removed: removed ? removed[1] : "0",
  };
}

function FolderIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6.5h4.5l1.6 1.6h7.9v8.4H3z" />
    </svg>
  );
}

function KindIcon({ kind }: { kind: IdxKind }) {
  const p = { width: 18, height: 18, viewBox: "0 0 20 20", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (kind === "code") return <svg {...p}><path d="M7.5 5 3.5 10l4 5M12.5 5l4 5-4 5" /></svg>;
  if (kind === "history") return <svg {...p}><circle cx="10" cy="10" r="6.5" /><path d="M10 6v4.2l3 1.8" /></svg>;
  return <svg {...p}><path d="M6 3h5l3.5 3.5V17H6z" /><path d="M11 3v3.5h3.5" /></svg>;
}
