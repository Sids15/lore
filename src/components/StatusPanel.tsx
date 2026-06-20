import { useEffect, useState } from "react";

import { fetchHealth, type HealthResponse } from "../lib/api";

/** Polling interval for the sidecar health check, in milliseconds. */
const POLL_INTERVAL_MS = 5000;

type SidecarStatus =
  | { kind: "loading" }
  | { kind: "connected"; health: HealthResponse }
  | { kind: "disconnected"; message: string };

/**
 * Shows the live status of the backend: the sidecar connection, the embedded
 * databases, and the Ollama runtime (including guidance when a model needs to
 * be pulled).
 *
 * Polls `/health` on an interval. The Tauri shell starts the sidecar
 * automatically, so this normally reaches "connected" within a second or two.
 */
export function StatusPanel() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function check() {
      try {
        const health = await fetchHealth(controller.signal);
        if (!cancelled) {
          setStatus({ kind: "connected", health });
        }
      } catch (error) {
        if (cancelled || controller.signal.aborted) {
          return;
        }
        const message = error instanceof Error ? error.message : "Unknown error";
        setStatus({ kind: "disconnected", message });
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
    <div className="status">
      <div className="status__pill">
        <span className={`status__dot status__dot--${pillTone(status)}`} aria-hidden />
        <span className="status__label">{pillLabel(status)}</span>
      </div>
      {status.kind === "connected" && <StatusDetails health={status.health} />}
    </div>
  );
}

/** Detail rows shown once the sidecar is connected. */
function StatusDetails({ health }: { health: HealthResponse }) {
  const dbReady = health.databases.sqlite && health.databases.lancedb;
  const ollama = health.ollama;

  return (
    <ul className="status__details">
      <li className={dbReady ? "is-ok" : "is-warn"}>
        Databases: {dbReady ? "ready" : "initializing"}
      </li>
      <li className={ollama.reachable && ollama.missing_models.length === 0 ? "is-ok" : "is-warn"}>
        Ollama: {ollamaSummary(health)}
      </li>
      {ollama.reachable &&
        ollama.missing_models.map((model) => (
          <li key={model} className="status__hint">
            Pull model: <code>ollama pull {model}</code>
          </li>
        ))}
    </ul>
  );
}

function ollamaSummary(health: HealthResponse): string {
  const { reachable, installed_models, missing_models } = health.ollama;
  if (!reachable) {
    return "not running — start Ollama";
  }
  if (missing_models.length > 0) {
    return `running, ${missing_models.length} model(s) missing`;
  }
  return `ready (${installed_models.length} model(s))`;
}

function pillTone(status: SidecarStatus): "loading" | "connected" | "disconnected" {
  return status.kind;
}

function pillLabel(status: SidecarStatus): string {
  switch (status.kind) {
    case "loading":
      return "Connecting to sidecar…";
    case "connected":
      return `Sidecar connected — ${status.health.service} v${status.health.version}`;
    case "disconnected":
      return `Sidecar disconnected (${status.message})`;
  }
}
