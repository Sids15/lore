import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { askQuestionStream, type AnswerResponse, type ConversationTurn } from "../lib/api";
import { SourceViewer, type SourceTarget } from "./SourceViewer";

/** Most-recent completed turns sent as context for a follow-up question. */
const CONVERSATION_TURNS = 6;

interface QaEntry {
  id: string;
  question: string;
  answer: AnswerResponse;
  status?: string; // live stage while streaming (generating/verifying/refining)
  latencyMs?: number; // wall-clock duration once the stream finishes
}

/** A fresh, empty answer to fill in as the stream arrives. */
const EMPTY_ANSWER: AnswerResponse = {
  answer: "",
  sources: [],
  grounded: true,
  unsupported: [],
  categories: [],
  graph_used: false,
  corrected: false,
  commits: [],
  docs: [],
};

function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/**
 * Ask natural-language questions about the indexed repository. The answer streams
 * in token-by-token (with a Stop button and a latency readout); each result is a
 * Markdown card with a faithfulness badge, query-type tags, and sources/commits/docs,
 * kept as a scrollable history (newest first).
 */
export function QueryPanel() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QaEntry[]>([]);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // drives the live latency readout
  const [viewing, setViewing] = useState<SourceTarget | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const startedRef = useRef<number>(0);

  // While a stream is in flight, re-render a few times a second so the elapsed
  // latency updates.
  useEffect(() => {
    if (!streamingId) return;
    const timer = window.setInterval(() => setTick(performance.now()), 100);
    return () => window.clearInterval(timer);
  }, [streamingId]);

  const patch = useCallback((id: string, fn: (entry: QaEntry) => QaEntry) => {
    setHistory((prev) => prev.map((e) => (e.id === id ? fn(e) : e)));
  }, []);

  const ask = useCallback(async () => {
    const q = question.trim();
    if (!q || streamingId) return;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    // The conversation context: prior completed turns, oldest-first, capped.
    const priorTurns: ConversationTurn[] = history
      .filter((e) => e.answer.answer.trim() !== "")
      .map((e) => ({ question: e.question, answer: e.answer.answer }))
      .reverse()
      .slice(-CONVERSATION_TURNS);

    const id = crypto.randomUUID();
    setHistory((prev) => [{ id, question: q, answer: { ...EMPTY_ANSWER }, status: "generating" }, ...prev]);
    setQuestion("");
    setError(null);
    setStreamingId(id);
    startedRef.current = performance.now();
    setTick(startedRef.current);

    try {
      await askQuestionStream(
        q,
        {
          onMeta: (m) =>
            patch(id, (e) => ({
              ...e,
              answer: {
                ...e.answer,
                categories: m.categories,
                graph_used: m.graph_used,
                sources: m.sources,
                commits: m.commits,
                docs: m.docs,
              },
            })),
          onToken: (text) =>
            patch(id, (e) => ({ ...e, answer: { ...e.answer, answer: e.answer.answer + text } })),
          onStatus: (stage) => patch(id, (e) => ({ ...e, status: stage })),
          onReplace: () => patch(id, (e) => ({ ...e, answer: { ...e.answer, answer: "" } })),
          onFinal: (f) =>
            patch(id, (e) => ({
              ...e,
              status: undefined,
              answer: {
                ...e.answer,
                grounded: f.grounded,
                unsupported: f.unsupported,
                corrected: f.corrected,
              },
            })),
          onError: (detail) => setError(detail),
        },
        controller.signal,
        priorTurns,
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Failed to get an answer");
      }
    } finally {
      if (controllerRef.current === controller) {
        const ms = Math.round(performance.now() - startedRef.current);
        patch(id, (e) => ({ ...e, status: undefined, latencyMs: ms }));
        setStreamingId(null);
      }
    }
  }, [question, streamingId, history, patch]);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  const newChat = useCallback(() => {
    controllerRef.current?.abort();
    setHistory([]);
    setError(null);
  }, []);

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Submit on Enter; allow Shift+Enter for a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  };

  return (
    <section className="query">
      <div className="query__header">
        <h2 className="query__title">Ask</h2>
        {history.length > 0 && (
          <button className="query__newchat" onClick={newChat}>
            New chat
          </button>
        )}
      </div>

      <textarea
        className="query__input"
        value={question}
        onChange={(e) => setQuestion(e.currentTarget.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask a question about the indexed code… (Enter to send, Shift+Enter for newline)"
        rows={3}
        disabled={streamingId !== null}
      />

      <div className="query__controls">
        <button
          className="query__btn"
          onClick={() => void ask()}
          disabled={streamingId !== null || question.trim() === ""}
        >
          {streamingId ? "Streaming…" : "Ask"}
        </button>
        {streamingId && (
          <button className="query__btn query__btn--stop" onClick={stop}>
            Stop
          </button>
        )}
      </div>

      {error && <p className="query__error">{error}</p>}

      <div className="query__history">
        {history.map((entry) => {
          const streaming = entry.id === streamingId;
          const latencyLabel = streaming
            ? formatMs(tick - startedRef.current)
            : entry.latencyMs != null
              ? formatMs(entry.latencyMs)
              : null;
          return (
            <AnswerCard
              key={entry.id}
              entry={entry}
              streaming={streaming}
              latencyLabel={latencyLabel}
              onOpenSource={setViewing}
            />
          );
        })}
      </div>

      {viewing && <SourceViewer target={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}

function AnswerCard({
  entry,
  streaming,
  latencyLabel,
  onOpenSource,
}: {
  entry: QaEntry;
  streaming: boolean;
  latencyLabel: string | null;
  onOpenSource: (target: SourceTarget) => void;
}) {
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
        {streaming ? (
          <span className="query__badge query__badge--stream">{entry.status ?? "generating"}…</span>
        ) : (
          <span className={`query__badge query__badge--${answer.grounded ? "ok" : "warn"}`}>
            {answer.grounded ? "grounded" : "ungrounded"}
          </span>
        )}
        {answer.categories.map((c) => (
          <span key={c} className="query__tag">{c}</span>
        ))}
        {answer.graph_used && <span className="query__tag query__tag--graph">graph</span>}
        {answer.corrected && (
          <span className="query__tag query__tag--corrected">self-corrected</span>
        )}
        {latencyLabel && <span className="query__latency">{latencyLabel}</span>}
        {!streaming && (
          <button className="query__copy" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      <div className="query__answer-md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer.answer}</ReactMarkdown>
        {streaming && <span className="query__cursor">▍</span>}
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
                <button
                  className="query__source-open"
                  onClick={() =>
                    onOpenSource({
                      repo: s.repo,
                      path: s.file_path,
                      start: s.start_line,
                      end: s.end_line,
                    })
                  }
                  title="Open in source viewer"
                >
                  <code>{s.symbol}</code>
                  <span className="query__source-loc">
                    {s.file_path}:{s.start_line}-{s.end_line}
                  </span>
                  <span className="query__source-kind">{s.kind}</span>
                </button>
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

      {answer.docs.length > 0 && (
        <div className="query__sources">
          <h3 className="query__sources-title">Docs</h3>
          <ul>
            {answer.docs.map((d) => (
              <li key={d.chunk_id}>
                <button
                  className="query__source-open"
                  onClick={() =>
                    onOpenSource({
                      repo: d.repo,
                      path: d.file_path,
                      start: d.start_line,
                      end: d.end_line,
                    })
                  }
                  title="Open in source viewer"
                >
                  <code>{d.heading || d.file_path}</code>
                  <span className="query__source-loc">
                    {d.file_path}:{d.start_line}-{d.end_line}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
