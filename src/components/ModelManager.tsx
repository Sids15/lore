import { useCallback, useEffect, useState } from "react";

import { fetchHealth, pullModelStream, type HealthResponse } from "../lib/api";

const POLL_INTERVAL_MS = 5000;

/**
 * The model-setup banner. Appears only when required Ollama models are missing,
 * and lets the user pull them (with a progress bar) without leaving the app.
 */
export function ModelManager() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [pct, setPct] = useState(0);
  const [current, setCurrent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setHealth(await fetchHealth());
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const missing = health?.ollama.missing_models ?? [];

  const pull = useCallback(async () => {
    setPulling(true);
    setError(null);
    setPct(0);
    try {
      for (const model of missing) {
        setCurrent(model.split(":")[0]);
        await pullModelStream(model, {
          onProgress: (e) =>
            setPct(e.total ? Math.round(((e.completed ?? 0) / e.total) * 100) : 0),
          onError: (detail) => setError(detail),
        });
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pull failed");
    } finally {
      setPulling(false);
    }
  }, [missing, refresh]);

  if (!health || missing.length === 0 || dismissed) return null;

  return (
    <div className="banner">
      <span className="banner__icon" aria-hidden>!</span>
      <div>
        <div className="banner__title">Local models required</div>
        <div className="banner__sub">
          Lore runs entirely on-device. Pull{" "}
          {missing.map((m, i) => (
            <span key={m}>
              {i > 0 && " + "}
              <code>{m}</code>
            </span>
          ))}{" "}
          to begin.
        </div>
        {error && <div className="banner__sub" style={{ color: "var(--danger)" }}>{error}</div>}
      </div>

      {pulling ? (
        <div className="banner__progress">
          <div className="banner__bar">
            <div className="banner__bar-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="banner__pct">
            {pct}% · {current}
          </span>
        </div>
      ) : (
        <div className="banner__actions">
          <button className="btn btn--ghost" onClick={() => setDismissed(true)}>
            Later
          </button>
          <button className="btn btn--warn" onClick={() => void pull()}>
            Pull models
          </button>
        </div>
      )}
    </div>
  );
}
