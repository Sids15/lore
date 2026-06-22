import { useCallback, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { askQuestion, type AnswerResponse } from "../lib/api";

interface QaEntry {
  id: string;
  question: string;
  answer: AnswerResponse;
}

/**
 * Ask natural-language questions about the indexed repository. Answers render as
 * Markdown, with a faithfulness badge, query-type tags, sources/commits, and a
 * copy button — kept as a scrollable history (newest first).
 */
export function QueryPanel() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QaEntry[]>([]);
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
    try {
      const answer = await askQuestion(q, controller.signal);
      const entry: QaEntry = { id: crypto.randomUUID(), question: q, answer };
      setHistory((prev) => [entry, ...prev]);
      setQuestion("");
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

      <div className="query__history">
        {history.map((entry) => (
          <AnswerCard key={entry.id} entry={entry} />
        ))}
      </div>
    </section>
  );
}

function AnswerCard({ entry }: { entry: QaEntry }) {
  const { question, answer } = entry;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answer.answer);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable; ignore.
    }
  };

  return (
    <article className="query__answer">
      <p className="query__question">{question}</p>

      <div className="query__answer-head">
        <span className={`query__badge query__badge--${answer.grounded ? "ok" : "warn"}`}>
          {answer.grounded ? "grounded" : "ungrounded"}
        </span>
        {answer.categories.map((c) => (
          <span key={c} className="query__tag">{c}</span>
        ))}
        {answer.graph_used && <span className="query__tag query__tag--graph">graph</span>}
        {answer.corrected && (
          <span className="query__tag query__tag--corrected">self-corrected</span>
        )}
        <button className="query__copy" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <div className="query__answer-md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer.answer}</ReactMarkdown>
      </div>

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
  );
}
