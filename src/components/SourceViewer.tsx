import { useEffect, useState } from "react";

import { fetchSource, type SourceView } from "../lib/api";

/** A cited location to open in the viewer. */
export interface SourceTarget {
  repo: string;
  path: string;
  start: number;
  end: number;
}

/**
 * Modal overlay showing the lines around a cited range, with the cited band
 * highlighted. Fetches the window from the sidecar's `/source` endpoint.
 */
export function SourceViewer({
  target,
  onClose,
}: {
  target: SourceTarget;
  onClose: () => void;
}) {
  const [view, setView] = useState<SourceView | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch the window whenever the target changes.
  useEffect(() => {
    const controller = new AbortController();
    setView(null);
    setError(null);
    fetchSource(target.repo, target.path, target.start, target.end, controller.signal)
      .then(setView)
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Failed to load source");
        }
      });
    return () => controller.abort();
  }, [target]);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="viewer__overlay" onClick={onClose}>
      <div className="viewer" onClick={(e) => e.stopPropagation()}>
        <div className="viewer__head">
          <span className="viewer__path">
            {target.path}:{target.start}-{target.end}
          </span>
          <button className="viewer__close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {error && <p className="viewer__error">{error}</p>}
        {!view && !error && <p className="viewer__loading">Loading…</p>}

        {view && (
          <pre className="viewer__code">
            {view.lines.map((line, i) => {
              const lineNo = view.window_start + i;
              const cited = lineNo >= view.start_line && lineNo <= view.end_line;
              return (
                <div
                  key={lineNo}
                  className={`viewer__line${cited ? " viewer__line--cited" : ""}`}
                >
                  <span className="viewer__gutter">{lineNo}</span>
                  <span className="viewer__text">{line || " "}</span>
                </div>
              );
            })}
          </pre>
        )}
      </div>
    </div>
  );
}
