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

  return (
    <section className="refactor">
      <div className="refactor__head">
        <h2 className="refactor__title">Refactor</h2>
        <button className="refactor__refresh" onClick={() => void load()} disabled={loading}>
          {loading ? "Scanning…" : candidates ? "Rescan" : "Scan"}
        </button>
      </div>

      {error && <p className="refactor__error">{error}</p>}
      {candidates && candidates.length === 0 && (
        <p className="refactor__empty">No structural issues found.</p>
      )}

      <div className="refactor__list">
        {candidates?.map((c) => {
          const proposal = proposals[c.id];
          return (
            <article key={c.id} className="refactor__card">
              <div className="refactor__card-head">
                <span className={`refactor__badge refactor__badge--${c.severity}`}>
                  {c.severity}
                </span>
                <span className="refactor__kind">{c.kind}</span>
                <h3 className="refactor__card-title">{c.title}</h3>
              </div>

              <p className="refactor__summary">{c.summary}</p>

              <div className="refactor__files">
                {c.files.map((file) => (
                  <button
                    key={file}
                    className="refactor__file"
                    onClick={() => repo && setViewing({ repo, path: file, start: 1, end: 1 })}
                    disabled={!repo}
                    title="Open file"
                  >
                    {file}
                  </button>
                ))}
              </div>

              {!proposal && (
                <button className="refactor__suggest" onClick={() => void suggest(c)}>
                  Suggest fix
                </button>
              )}
              {proposal?.loading && <p className="refactor__status">Thinking…</p>}
              {proposal?.error && <p className="refactor__error">{proposal.error}</p>}
              {proposal?.text && (
                <div className="refactor__proposal">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{proposal.text}</ReactMarkdown>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {viewing && <SourceViewer target={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}
