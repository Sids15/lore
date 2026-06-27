import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  askQuestionStream,
  type AnswerResponse,
  type CommitHit,
  type ConversationTurn,
  type DocHit,
  type Source,
} from "../lib/api";
import { LoreMark } from "./LoreMark";
import { SourceViewer, type SourceTarget } from "./SourceViewer";

const CONVERSATION_TURNS = 6;

const EXAMPLES: { q: string; tag: string }[] = [
  { q: "How does session authentication work?", tag: "code" },
  { q: "Who last changed the auth module, and why?", tag: "history" },
  { q: "Where are database migrations applied?", tag: "code" },
  { q: "What is the rate-limit policy for the public API?", tag: "code" },
];

interface QaEntry {
  id: string;
  question: string;
  answer: AnswerResponse;
  status?: string;
  latencyMs?: number;
}

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

export function QueryPanel() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QaEntry[]>([]);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [viewing, setViewing] = useState<SourceTarget | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const startedRef = useRef<number>(0);

  useEffect(() => {
    if (!streamingId) return;
    const timer = window.setInterval(() => setTick(performance.now()), 100);
    return () => window.clearInterval(timer);
  }, [streamingId]);

  const patch = useCallback((id: string, fn: (entry: QaEntry) => QaEntry) => {
    setHistory((prev) => prev.map((e) => (e.id === id ? fn(e) : e)));
  }, []);

  const runAsk = useCallback(
    async (override?: string) => {
      const q = (override ?? question).trim();
      if (!q || streamingId) return;

      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

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
    },
    [question, streamingId, history, patch],
  );

  const stop = useCallback(() => controllerRef.current?.abort(), []);
  const newChat = useCallback(() => {
    controllerRef.current?.abort();
    setHistory([]);
    setError(null);
  }, []);

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void runAsk();
    }
  };

  const liveLatency = streamingId ? formatMs(tick - startedRef.current) : null;

  return (
    <section className="ask">
      <header className="ws__head">
        <div>
          <h2 className="ws__title">Ask</h2>
          <p className="ws__sub">
            Interrogate your codebase in plain language. Every answer is grounded in cited evidence.
          </p>
        </div>
        {history.length > 0 && (
          <button className="btn btn--ghost" onClick={newChat}>+ New chat</button>
        )}
      </header>

      <div className="ask__scroll">
        <div className="ask__inner">
          {error && <p className="ask__error">{error}</p>}

          {history.length === 0 ? (
            <div className="empty">
              <div className="empty__tile"><LoreMark size={30} /></div>
              <h2 className="empty__title">Ask anything about your codebase</h2>
              <p className="empty__text">
                Lore reads your code, git history, and docs locally and answers with exact
                file-and-line citations — nothing leaves this machine.
              </p>
              <div className="eyebrow" style={{ marginTop: 8 }}>Try asking</div>
              <div className="ask__examples">
                {EXAMPLES.map((ex) => (
                  <button key={ex.q} className="ask__example" onClick={() => void runAsk(ex.q)}>
                    <span className="ask__example-tag">{ex.tag}</span>
                    <span>{ex.q}</span>
                    <span className="ask__example-arrow" aria-hidden>→</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            history.map((entry) => {
              const streaming = entry.id === streamingId;
              const latency = streaming
                ? null
                : entry.latencyMs != null
                  ? formatMs(entry.latencyMs)
                  : null;
              return (
                <AnswerCard
                  key={entry.id}
                  entry={entry}
                  streaming={streaming}
                  latency={latency}
                  onOpenSource={setViewing}
                />
              );
            })
          )}
        </div>
      </div>

      <div className="composer">
        <div className="composer__inner">
          <div className="composer__box">
            <textarea
              className="composer__input"
              value={question}
              onChange={(e) => setQuestion(e.currentTarget.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask about code, history, docs, or architecture…  (Enter to send · Shift+Enter for newline)"
              rows={2}
              disabled={streamingId !== null}
            />
            <div className="composer__row">
              <span className="composer__scope">scope: code · history · docs</span>
              <div className="composer__controls">
                {streamingId ? (
                  <>
                    {liveLatency && <span className="composer__live">{liveLatency}</span>}
                    <button className="btn btn--danger" onClick={stop}>■ Stop</button>
                  </>
                ) : (
                  <button
                    className="btn btn--primary"
                    onClick={() => void runAsk()}
                    disabled={question.trim() === ""}
                  >
                    Send ↵
                  </button>
                )}
              </div>
            </div>
          </div>
          <div className="composer__reassure">
            <span className="composer__reassure-dot" aria-hidden />
            Answers are generated locally and never leave this machine.
          </div>
        </div>
      </div>

      {viewing && <SourceViewer target={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}

function AnswerCard({
  entry,
  streaming,
  latency,
  onOpenSource,
}: {
  entry: QaEntry;
  streaming: boolean;
  latency: string | null;
  onOpenSource: (target: SourceTarget) => void;
}) {
  const { question, answer } = entry;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answer.answer);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable */
    }
  };

  const verifying = entry.status === "verifying";
  const citations = answer.sources.length + answer.docs.length + answer.commits.length;

  return (
    <div>
      <div className="ans__q">
        <span className="ans__you">you</span>
        <span className="ans__qtext">{question}</span>
      </div>

      <article className="ans">
        <div className="ans__meta">
          {streaming ? (
            <span className={`ans__badge ${verifying ? "ans__badge--verify" : "ans__badge--stream"}`}>
              <span className="ans__livedot" aria-hidden />
              {verifying ? "Verifying sources…" : "Generating answer…"}
            </span>
          ) : (
            <span className={`ans__badge ${answer.grounded ? "ans__badge--ok" : "ans__badge--warn"}`}>
              {answer.grounded ? "✓ Grounded" : "◐ Partially supported"}
            </span>
          )}
          {answer.categories.map((c) => (
            <span key={c} className="ans__tag">{c}</span>
          ))}
          {answer.corrected && <span className="ans__tag">self-corrected</span>}
          {latency && <span className="ans__latency">{latency}</span>}
          {!streaming && (
            <button className="ans__copy" onClick={() => void copy()}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
          )}
        </div>

        <div className="ans__prose">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer.answer}</ReactMarkdown>
          {streaming && <span className="ans__cursor" aria-hidden />}
        </div>

        {!answer.grounded && answer.unsupported.length > 0 && (
          <ul className="ans__unsupported">
            {answer.unsupported.map((claim, i) => <li key={i}>{claim}</li>)}
          </ul>
        )}

        {!streaming && citations > 0 && (
          <div className="ans__sources">
            <div className="ans__sources-head">
              <span className="eyebrow">Sources</span>
              <span className="ans__sources-count">
                {citations} citation{citations === 1 ? "" : "s"}
              </span>
            </div>
            {answer.sources.map((s) => (
              <CodeSourceRow key={s.chunk_id} s={s} onOpen={onOpenSource} />
            ))}
            {answer.docs.map((d) => (
              <DocSourceRow key={d.chunk_id} d={d} onOpen={onOpenSource} />
            ))}
            {answer.commits.map((c) => (
              <CommitSourceRow key={c.sha} c={c} />
            ))}
          </div>
        )}
      </article>
    </div>
  );
}

function CodeSourceRow({ s, onOpen }: { s: Source; onOpen: (t: SourceTarget) => void }) {
  return (
    <button
      className="src"
      onClick={() => onOpen({ repo: s.repo, path: s.file_path, start: s.start_line, end: s.end_line })}
    >
      <span className="src__kind">{s.kind}</span>
      <span className="src__sym">{s.symbol}</span>
      <span className="src__meta">{s.file_path}:{s.start_line}–{s.end_line}</span>
      <span className="src__arrow" aria-hidden>↗</span>
    </button>
  );
}

function DocSourceRow({ d, onOpen }: { d: DocHit; onOpen: (t: SourceTarget) => void }) {
  return (
    <button
      className="src"
      onClick={() => onOpen({ repo: d.repo, path: d.file_path, start: d.start_line, end: d.end_line })}
    >
      <span className="src__kind">doc</span>
      <span className="src__sym">{d.heading || d.file_path}</span>
      <span className="src__meta">{d.file_path}:{d.start_line}–{d.end_line}</span>
      <span className="src__arrow" aria-hidden>↗</span>
    </button>
  );
}

function CommitSourceRow({ c }: { c: CommitHit }) {
  return (
    <div className="src" style={{ cursor: "default" }}>
      <span className="src__kind">commit</span>
      <span className="src__sym">{c.sha.slice(0, 7)}</span>
      <span className="src__meta">{c.author} · {c.committed_at.slice(0, 10)}</span>
    </div>
  );
}
