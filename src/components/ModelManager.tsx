import { useCallback, useEffect, useState } from "react";

import { fetchHealth, pullModelStream, type HealthResponse } from "../lib/api";

/** Re-check health on this cadence so the banner self-hides once models land. */
const POLL_INTERVAL_MS = 5000;

interface PullState {
  status: string;
  pct: number | null;
  error?: string;
}

/**
 * A banner that appears only when the required Ollama models aren't ready. It
 * lets the user pull each missing model from inside the app (with a live
 * progress bar) instead of running `ollama pull` in a terminal. Renders nothing
 * when Ollama is reachable and no models are missing.
 */
export function ModelManager() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [pulls, setPulls] = useState<Record<string, PullState>>({});

  const refresh = useCallback(async () => {
    try {
      setHealth(await fetchHealth());
    } catch {
      setHealth(null); // sidecar unreachable; StatusPanel surfaces that
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const pull = useCallback(
    async (model: string) => {
      setPulls((p) => ({ ...p, [model]: { status: "starting…", pct: null } }));
      try {
        await pullModelStream(model, {
          onProgress: (e) =>
            setPulls((p) => ({
              ...p,
              [model]: {
                status: e.status,
                pct: e.total ? Math.round(((e.completed ?? 0) / e.total) * 100) : null,
              },
            })),
          onError: (detail) =>
            setPulls((p) => ({ ...p, [model]: { status: "error", pct: null, error: detail } })),
        });
      } catch (err) {
        const detail = err instanceof Error ? err.message : "Pull failed";
        setPulls((p) => ({ ...p, [model]: { status: "error", pct: null, error: detail } }));
        return;
      }
      // Done: drop the local state and re-check health (the row disappears once
      // the model is installed).
      setPulls((p) => {
        const next = { ...p };
        delete next[model];
        return next;
      });
      void refresh();
    },
    [refresh],
  );

  if (!health) return null;
  const { ollama } = health;
  if (ollama.reachable && ollama.missing_models.length === 0) return null;

  return (
    <div className="models">
      {!ollama.reachable ? (
        <p className="models__hint">
          Ollama isn’t running. Start it, then Lore can pull the models it needs.
        </p>
      ) : (
        <>
          <p className="models__title">Required models missing — pull them to enable answers:</p>
          <ul className="models__list">
            {ollama.missing_models.map((model) => {
              const state = pulls[model];
              return (
                <li key={model} className="models__row">
                  <code className="models__name">{model}</code>
                  {!state ? (
                    <button className="models__pull" onClick={() => void pull(model)}>
                      Pull
                    </button>
                  ) : (
                    <div className="models__progress">
                      {state.pct !== null && (
                        <div className="models__bar">
                          <div className="models__bar-fill" style={{ width: `${state.pct}%` }} />
                        </div>
                      )}
                      <span className="models__status">
                        {state.error
                          ? `Error: ${state.error}`
                          : `${state.status}${state.pct !== null ? ` ${state.pct}%` : ""}`}
                      </span>
                      {state.error && (
                        <button className="models__pull" onClick={() => void pull(model)}>
                          Retry
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
