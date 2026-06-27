import { useEffect, useState } from "react";

import { fetchSource, type SourceView } from "../lib/api";

export interface SourceTarget {
  repo: string;
  path: string;
  start: number;
  end: number;
}

/**
 * The code-viewer modal: shows the file around a cited range with the cited band
 * highlighted. Opens from any source citation or file chip.
 */
export function SourceViewer({ target, onClose }: { target: SourceTarget; onClose: () => void }) {
  const [view, setView] = useState<SourceView | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="cv__overlay" onClick={onClose}>
      <div className="cv" onClick={(e) => e.stopPropagation()}>
        <div className="cv__bar">
          <span className="cv__kind">code</span>
          <span className="cv__path">{target.path}</span>
          <span className="cv__sub">lines {target.start}–{target.end}</span>
          <span className="cv__cited">✓ cited band</span>
          <button className="cv__close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {error && <p className="cv__error">{error}</p>}
        {!view && !error && <p className="cv__loading">Loading…</p>}

        {view && (
          <div className="cv__body">
            {view.lines.map((line, i) => {
              const lineNo = view.window_start + i;
              const cited = lineNo >= view.start_line && lineNo <= view.end_line;
              return (
                <div key={lineNo} className={`cv__line${cited ? " cv__line--cited" : ""}`}>
                  <span className="cv__gutter">{lineNo}</span>
                  <span className="cv__text">{line || " "}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
