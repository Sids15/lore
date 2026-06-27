import { useEffect, useState, type ReactNode } from "react";

import { fetchHealth, type HealthResponse } from "../lib/api";

const POLL_INTERVAL_MS = 5000;

type SidecarStatus =
  | { kind: "loading" }
  | { kind: "connected"; health: HealthResponse }
  | { kind: "disconnected"; message: string };

/**
 * The full-width status bar. Polls `/health` and shows the sidecar, database, and
 * Ollama state, with the "100% local" affirmation pinned right.
 */
export function StatusPanel({ repo }: { repo?: string | null }) {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    async function check() {
      try {
        const health = await fetchHealth(controller.signal);
        if (!cancelled) setStatus({ kind: "connected", health });
      } catch (error) {
        if (cancelled || controller.signal.aborted) return;
        setStatus({ kind: "disconnected", message: error instanceof Error ? error.message : "error" });
      }
    }
    void check();
    const timer = window.setInterval(() => void check(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  return (
    <footer className="status">
      {repo && (
        <>
          <span className="status__seg">
            <span className="status__sq" aria-hidden />
            {repo}
          </span>
          <span className="status__sep" />
        </>
      )}
      {status.kind === "loading" && (
        <Seg dot="load" label="Connecting…" />
      )}
      {status.kind === "disconnected" && (
        <Seg dot="bad" label="Sidecar offline" />
      )}
      {status.kind === "connected" && <ConnectedSegs health={status.health} />}

      <div className="status__right">
        <span className="status__lock" aria-hidden>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
            <rect x="3.2" y="7" width="9.6" height="6.4" rx="1.4" />
            <path d="M5 7V5.4a3 3 0 0 1 6 0V7" />
          </svg>
        </span>
        100% local · no cloud
      </div>
    </footer>
  );
}

function ConnectedSegs({ health }: { health: HealthResponse }) {
  const dbReady = health.databases.sqlite && health.databases.lancedb;
  const o = health.ollama;
  const ollama = !o.reachable
    ? "Ollama · offline"
    : o.missing_models.length > 0
      ? `Ollama · ${o.missing_models.length} missing`
      : `Ollama · ${o.installed_models.length} models`;
  return (
    <>
      <Seg dot="ok" label="sidecar" />
      <span className="status__sep" />
      <Seg dot={dbReady ? "ok" : "warn"} label={dbReady ? "db ready" : "db init"} />
      <span className="status__sep" />
      <Seg dot={o.reachable && o.missing_models.length === 0 ? "ok" : "warn"} label={ollama} />
    </>
  );
}

function Seg({ dot, label }: { dot: "ok" | "warn" | "bad" | "load"; label: ReactNode }) {
  return (
    <span className="status__seg">
      <span className={`status__dot status__dot--${dot}`} aria-hidden />
      {label}
    </span>
  );
}
