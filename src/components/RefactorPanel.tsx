import { useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { fetchRefactor, suggestRefactor, type RefactorCandidate } from "../lib/api";
import { SourceViewer, type SourceTarget } from "./SourceViewer";

interface ProposalState {
  loading: boolean;
  text?: string;
  error?: string;
}

/**
 * Lists structural refactoring candidates (cycles, coupling hubs, architecture
 * violations) for the indexed repo. Each candidate's files open in the source
 * viewer, and a grounded LLM fix can be requested on demand.
 */
export function RefactorPanel() {
  const [repo, setRepo] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<RefactorCandidate[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Record<string, ProposalState>>({});
  const [viewing, setViewing] = useState<SourceTarget | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchRefactor();
      setRepo(res.repo);
      setCandidates(res.candidates);
      setProposals({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load candidates");
    } finally {
      setLoading(false);
    }
  }, []);

  const suggest = useCallback(async (candidate: RefactorCandidate) => {
    setProposals((p) => ({ ...p, [candidate.id]: { loading: true } }));
    try {
      const text = await suggestRefactor(candidate);
      setProposals((p) => ({ ...p, [candidate.id]: { loading: false, text } }));
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Failed to suggest a fix";
      setProposals((p) => ({ ...p, [candidate.id]: { loading: false, error: detail } }));
    }
  }, []);

  const sevCount = (s: string) => candidates?.filter((c) => c.severity === s).length ?? 0;
  const summary = candidates
    ? `${candidates.length} candidate${candidates.length === 1 ? "" : "s"} found — ` +
      `${sevCount("high")} high, ${sevCount("medium")} medium, ${sevCount("low")} low.`
    : "";

  return (
    <section className="ws">
      <header className="ws__head">
        <div>
          <h2 className="ws__title">Refactor</h2>
          <p className="ws__sub">
            Lore scans for structural problems and proposes grounded fixes you can review before
            acting.
          </p>
        </div>
        <button className="btn btn--primary" onClick={() => void load()} disabled={loading}>
          {loading ? "Scanning…" : candidates ? "Re-scan" : "Scan codebase"}
        </button>
      </header>

      <div className="ws__body">
        {error && <p className="rf__error">{error}</p>}

        {loading && (
          <div className="ev__running">
            <div className="spinner" aria-hidden />
            <div>Scanning the dependency graph…</div>
          </div>
        )}

        {!candidates && !loading && (
          <div className="empty">
            <div className="empty__tile"><RefactorGlyph /></div>
            <h2 className="empty__title">Nothing scanned yet</h2>
            <p className="empty__text">
              Run a scan to surface dependency cycles, coupling hubs, and architecture violations —
              ranked by severity, each with the exact files involved.
            </p>
          </div>
        )}

        {candidates && candidates.length === 0 && (
          <div className="empty">
            <div className="empty__tile"><RefactorGlyph /></div>
            <h2 className="empty__title">No structural issues found</h2>
            <p className="empty__text">Nothing stands out in the dependency graph. Clean.</p>
          </div>
        )}

        {candidates && candidates.length > 0 && (
          <>
            <p className="rf__summary">{summary}</p>
            <div className="rf__list">
              {candidates.map((c) => {
                const sev = c.severity === "medium" ? "med" : c.severity;
                const proposal = proposals[c.id];
                return (
                  <article key={c.id} className={`rfc rfc--${sev}`}>
                    <div className="rfc__head">
                      <span className={`rfc__sev rfc__sev--${sev}`}>{c.severity}</span>
                      <span className="rfc__kind">{c.kind}</span>
                      <span className="rfc__title">{c.title}</span>
                    </div>

                    <p className="rfc__summary">{c.summary}</p>

                    <div className="rfc__files">
                      {c.files.map((file) => (
                        <button
                          key={file}
                          className="rfc__file"
                          onClick={() => repo && setViewing({ repo, path: file, start: 1, end: 1 })}
                          disabled={!repo}
                        >
                          {file} <span aria-hidden>↗</span>
                        </button>
                      ))}
                    </div>

                    {!proposal ? (
                      <button className="btn btn--accent-outline rfc__suggest" onClick={() => void suggest(c)}>
                        ✦ Suggest fix
                      </button>
                    ) : (
                      <div className="rfc__fix">
                        <div className="rfc__fix-head">
                          <span className="eyebrow">Proposed fix</span>
                          {proposal.loading && <span className="rfc__fix-grounded">generating…</span>}
                          {proposal.text && <span className="rfc__fix-grounded">✓ grounded</span>}
                        </div>
                        {proposal.error ? (
                          <p className="rf__error">{proposal.error}</p>
                        ) : proposal.loading ? (
                          <p className="rfc__fix-body">Thinking…</p>
                        ) : (
                          <div className="rfc__fix-body">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{proposal.text ?? ""}</ReactMarkdown>
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </>
        )}
      </div>

      {viewing && <SourceViewer target={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}

function RefactorGlyph() {
  return (
    <svg width="26" height="26" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5.5" cy="5" r="1.8" />
      <circle cx="5.5" cy="15" r="1.8" />
      <circle cx="14.5" cy="10" r="1.8" />
      <path d="M5.5 6.8v6.4M5.5 10h4.2A3 3 0 0 0 12.7 7" />
    </svg>
  );
}
