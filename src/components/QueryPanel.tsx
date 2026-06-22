import { useCallback, useRef, useState } from "react";

import { askQuestion, type AnswerResponse } from "../lib/api";

/**
 * Ask a natural-language question about the indexed repository and show the
 * grounded answer, a faithfulness badge, and the source chunks it was built from.
 */
export function QueryPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const ask = useCallback(async () => {
    const q = question.trim();
    if (!q || loading) return;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await askQuestion(q, controller.signal));
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Failed to get an answer");
      }
    } finally {
      if (controllerRef.current === controller) setLoading(false);
    }
  }, [question, loading]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Submit on Enter; allow Shift+Enter for a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  };

  return (
    <section className="query">
      <h2 className="query__title">Ask</h2>

      <textarea
        className="query__input"
        value={question}
        onChange={(e) => setQuestion(e.currentTarget.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask a question about the indexed code… (Enter to send, Shift+Enter for newline)"
        rows={3}
        disabled={loading}
      />
      <button
        className="query__btn"
        onClick={() => void ask()}
        disabled={loading || question.trim() === ""}
      >
        {loading ? "Thinking…" : "Ask"}
      </button>

      {error && <p className="query__error">{error}</p>}

      {answer && (
        <article className="query__answer">
          <div className="query__answer-head">
            <span
              className={`query__badge query__badge--${answer.grounded ? "ok" : "warn"}`}
            >
              {answer.grounded ? "grounded" : "ungrounded"}
            </span>
            {answer.categories.map((c) => (
              <span key={c} className="query__tag">
                {c}
              </span>
            ))}
            {answer.graph_used && <span className="query__tag query__tag--graph">graph</span>}
            {answer.corrected && (
              <span className="query__tag query__tag--corrected">self-corrected</span>
            )}
          </div>

          <p className="query__answer-text">{answer.answer}</p>

          {!answer.grounded && answer.unsupported.length > 0 && (
            <ul className="query__unsupported">
              {answer.unsupported.map((claim, i) => (
                <li key={i}>{claim}</li>
              ))}
            </ul>
          )}

          {answer.sources.length > 0 && (
            <div className="query__sources">
              <h3 className="query__sources-title">Sources</h3>
              <ul>
                {answer.sources.map((s) => (
                  <li key={s.chunk_id}>
                    <code>{s.symbol}</code>
                    <span className="query__source-loc">
                      {s.file_path}:{s.start_line}-{s.end_line}
                    </span>
                    <span className="query__source-kind">{s.kind}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {answer.commits.length > 0 && (
            <div className="query__sources">
              <h3 className="query__sources-title">Commits</h3>
              <ul>
                {answer.commits.map((c) => (
                  <li key={c.sha}>
                    <code>{c.sha.slice(0, 7)}</code>
                    <span className="query__source-loc">
                      {c.author} · {c.committed_at.slice(0, 10)}
                    </span>
                    <span className="query__source-kind">{c.summary}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>
      )}
    </section>
  );
}
