import { useEffect, useState } from "react";

import { fetchHealth, type HealthResponse } from "../lib/api";

/** Polling interval for the sidecar health check, in milliseconds. */
const POLL_INTERVAL_MS = 5000;

type SidecarStatus =
  | { kind: "loading" }
  | { kind: "connected"; health: HealthResponse }
  | { kind: "disconnected"; message: string };

/**
 * Shows the live connection status of the Python sidecar.
 *
 * Polls `/health` on an interval and reflects the result with a colored
 * indicator. The Tauri shell starts the sidecar automatically, so this normally
 * transitions from "Connecting" to "Connected" within a second or two.
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
      <span className={`status__dot status__dot--${status.kind}`} aria-hidden />
      <span className="status__label">{describe(status)}</span>
    </div>
  );
}

function describe(status: SidecarStatus): string {
  switch (status.kind) {
    case "loading":
      return "Connecting to sidecar…";
    case "connected": {
      const { service, version, databases } = status.health;
      const dbs = `DBs ${databases.sqlite && databases.lancedb ? "ready" : "initializing"}`;
      return `Sidecar connected — ${service} v${version} · ${dbs}`;
    }
    case "disconnected":
      return `Sidecar disconnected (${status.message})`;
  }
}
