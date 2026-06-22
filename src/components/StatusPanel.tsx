import { useEffect, useState } from "react";

import { fetchHealth, type HealthResponse } from "../lib/api";

/** Polling interval for the sidecar health check, in milliseconds. */
const POLL_INTERVAL_MS = 5000;

type SidecarStatus =
  | { kind: "loading" }
  | { kind: "connected"; health: HealthResponse }
  | { kind: "disconnected"; message: string };

type Tone = "loading" | "connected" | "degraded" | "disconnected";

/**
 * Compact backend health badge for the header. Polls `/health` and shows a
 * colored dot + short label; the full details (DBs, Ollama, pull commands) are
 * available on hover via the title attribute.
 */
export function StatusPanel() {
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
    <span className="statusbadge" title={detail(status)}>
      <span className={`statusbadge__dot statusbadge__dot--${tone(status)}`} aria-hidden />
      {label(status)}
    </span>
  );
}

function _ready(health: HealthResponse): boolean {
  const dbReady = health.databases.sqlite && health.databases.lancedb;
  const ollamaReady = health.ollama.reachable && health.ollama.missing_models.length === 0;
  return dbReady && ollamaReady;
}

function tone(status: SidecarStatus): Tone {
  if (status.kind !== "connected") return status.kind;
  return _ready(status.health) ? "connected" : "degraded";
}

function label(status: SidecarStatus): string {
  switch (status.kind) {
    case "loading":
      return "Connecting…";
    case "disconnected":
      return "Sidecar offline";
    case "connected": {
      const h = status.health;
      if (!h.ollama.reachable) return "Ollama offline";
      if (h.ollama.missing_models.length > 0) return "Models missing";
      if (!(h.databases.sqlite && h.databases.lancedb)) return "DBs initializing";
      return "Ready";
    }
  }
}

function detail(status: SidecarStatus): string {
  switch (status.kind) {
    case "loading":
      return "Connecting to the sidecar…";
    case "disconnected":
      return `Sidecar disconnected: ${status.message}`;
    case "connected": {
      const h = status.health;
      const dbs = `DBs: ${h.databases.sqlite && h.databases.lancedb ? "ready" : "initializing"}`;
      const ollama = !h.ollama.reachable
        ? "Ollama: not running"
        : h.ollama.missing_models.length > 0
          ? `Ollama: pull ${h.ollama.missing_models.join(", ")}`
          : `Ollama: ready (${h.ollama.installed_models.length} models)`;
      return `${h.service} v${h.version} · ${dbs} · ${ollama}`;
    }
  }
}
