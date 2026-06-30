import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { fetchSettings, updateSettings, type AppSettings } from "../lib/api";

/** A group of related settings rendered as a card. */
interface Group {
  title: string;
  note: string;
  rows: Row[];
}

/**
 * Plain-language help shown in a hover/focus tooltip. `what` explains the setting
 * in everyday terms; `effects` is two short lines describing the trade-off — for a
 * toggle, what happens when it's on vs. off; for a number/slider, higher vs. lower.
 */
interface Help {
  what: string;
  effects: [string, string];
}

type Row =
  | { kind: "toggle"; key: BoolKey; label: string; hint: string; help: Help }
  | { kind: "number"; key: NumKey; label: string; hint: string; min: number; max: number; step: number; help: Help }
  | { kind: "slider"; key: NumKey; label: string; hint: string; min: number; max: number; step: number; help: Help };

type BoolKey = {
  [K in keyof AppSettings]: AppSettings[K] extends boolean ? K : never;
}[keyof AppSettings];
type NumKey = {
  [K in keyof AppSettings]: AppSettings[K] extends number ? K : never;
}[keyof AppSettings];

const GROUPS: Group[] = [
  {
    title: "Retrieval",
    note: "How candidate code is found, ranked, and trimmed before the model sees it.",
    rows: [
      {
        kind: "toggle", key: "rerank_enabled", label: "Cross-encoder rerank",
        hint: "Re-score hybrid candidates for sharper relevance.",
        help: {
          what: "A second, smarter pass that re-orders the code snippets found so the best matches for your question come first.",
          effects: ["On — answers usually cite better-matching code (slightly slower).", "Off — faster, but the most relevant snippet can rank lower."],
        },
      },
      {
        kind: "toggle", key: "mmr_enabled", label: "MMR diversity",
        hint: "Drop near-duplicate chunks from the final selection.",
        help: {
          what: "Filters out near-identical snippets so the model sees a wider variety of evidence instead of the same code repeated.",
          effects: ["On — fewer repeats, more distinct sources.", "Off — you may get several copies of nearly the same code."],
        },
      },
      {
        kind: "slider", key: "mmr_lambda", label: "MMR λ", min: 0, max: 1, step: 0.05,
        hint: "1.0 = pure relevance, 0.0 = pure diversity.",
        help: {
          what: "Balances picking the most relevant snippets against the most varied ones (only matters when MMR diversity is on).",
          effects: ["Higher (toward 1) — favors relevance; may repeat similar code.", "Lower (toward 0) — favors variety; may include less-relevant code."],
        },
      },
      {
        kind: "toggle", key: "parent_expansion_enabled", label: "Parent-chunk expansion",
        hint: "Attach a method's class header + file imports as context.",
        help: {
          what: "Adds the surrounding context of each snippet — the class it lives in and the file's imports — so the model understands where the code sits.",
          effects: ["On — richer context, usually better answers.", "Off — leaner prompts with a little less surrounding context."],
        },
      },
      {
        kind: "toggle", key: "query_expansion_enabled", label: "Query expansion",
        hint: "RRF-fuse alternate phrasings on the first pass (opt-in).",
        help: {
          what: "Rephrases your question a few different ways and searches with all of them, then combines the results.",
          effects: ["On — catches relevant code your exact wording missed (slower, extra work).", "Off — searches with your wording only (faster)."],
        },
      },
      {
        kind: "number", key: "query_expansion_n", label: "Expansion phrasings", min: 1, max: 8, step: 1,
        hint: "How many alternate phrasings to retrieve.",
        help: {
          what: "How many reworded versions of your question to search with (only used when Query expansion is on).",
          effects: ["Higher — casts a wider net and finds more, but is slower.", "Lower — faster, with a narrower search."],
        },
      },
      {
        kind: "number", key: "retrieval_top_k", label: "Results per query (k)", min: 1, max: 30, step: 1,
        hint: "Chunks kept after reranking.",
        help: {
          what: "How many code snippets to keep and hand to the model for each search.",
          effects: ["Higher — more evidence, but a longer, noisier prompt.", "Lower — tighter and faster, but it may miss something."],
        },
      },
    ],
  },
  {
    title: "Agent",
    note: "Routing, graph context, grounding, and self-correction behaviour.",
    rows: [
      {
        kind: "toggle", key: "router_enabled", label: "Question router",
        hint: "Classify each question to route retrieval.",
        help: {
          what: "Reads your question first and decides how to answer it — about code, history, docs, and so on.",
          effects: ["On — tailors the search to the kind of question asked.", "Off — uses one general strategy for every question."],
        },
      },
      {
        kind: "toggle", key: "graphrag_enabled", label: "GraphRAG context",
        hint: "Fold dependency/semantic-graph facts into answers.",
        help: {
          what: "Pulls in how pieces of code connect (what calls or depends on what) and folds those facts into the answer.",
          effects: ["On — better at “how does X relate to Y” questions.", "Off — answers from the snippets alone, without relationships."],
        },
      },
      {
        kind: "toggle", key: "grounding_enabled", label: "Grounding check",
        hint: "Second pass that verifies the answer against sources.",
        help: {
          what: "A second pass that checks the answer is actually backed by the cited code before it's shown to you.",
          effects: ["On — fewer made-up claims (a bit slower).", "Off — faster, but answers are not verified against the sources."],
        },
      },
      {
        kind: "toggle", key: "self_correct_enabled", label: "Self-correction",
        hint: "Re-retrieve and retry when an answer is ungrounded.",
        help: {
          what: "If the grounding check finds unsupported claims, it searches again and rewrites the answer.",
          effects: ["On — recovers from a weak first answer.", "Off — keeps the first answer as-is, even if weak."],
        },
      },
      {
        kind: "toggle", key: "iterative_enabled", label: "Iterative loop",
        hint: "Allow multiple correction rounds, not just one (opt-in).",
        help: {
          what: "Lets the self-correction try several search-and-rewrite rounds instead of just one.",
          effects: ["On — tries harder on tough questions (slower).", "Off — at most one retry."],
        },
      },
      {
        kind: "number", key: "iterative_max_rounds", label: "Max rounds", min: 2, max: 6, step: 1,
        hint: "Total passes incl. the first (iterative loop).",
        help: {
          what: "The most attempts allowed in the iterative loop, counting the first answer.",
          effects: ["Higher — more chances to get it right, but slower.", "Lower — quicker, with fewer retries."],
        },
      },
    ],
  },
  {
    title: "Conversation",
    note: "Multi-turn follow-up handling.",
    rows: [
      {
        kind: "toggle", key: "conversation_enabled", label: "Multi-turn",
        hint: "Condense follow-ups into standalone questions.",
        help: {
          what: "Lets a follow-up like “explain that” use the earlier conversation for context.",
          effects: ["On — follow-up questions understand what came before.", "Off — each question is answered on its own."],
        },
      },
    ],
  },
];

/** Live-editable settings for the retrieval/agent knobs. Applies on change. */
export function SettingsPanel() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number>(0);
  // Serializes PATCH sends so rapid edits leave in user-action order; the
  // (serialized) backend then persists them in that order — no out-of-order clobber.
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  useEffect(() => {
    let cancelled = false;
    fetchSettings()
      .then((s) => !cancelled && setSettings(s))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load settings"));
    return () => {
      cancelled = true;
    };
  }, []);

  const apply = useCallback((patch: Partial<AppSettings>) => {
    setError(null);
    setSettings((s) => (s ? { ...s, ...patch } : s)); // optimistic
    // Chain onto the queue so requests are sent one after another, in order. We
    // ignore the success body (the optimistic value already equals what was
    // persisted) to avoid an out-of-order response clobbering a newer edit.
    queue.current = queue.current
      .catch(() => {}) // a prior failure must not block later edits
      .then(async () => {
        try {
          await updateSettings(patch);
          setSavedAt(Date.now());
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to save");
          // Re-fetch authoritative state to revert correctly (no stale snapshot).
          try {
            setSettings(await fetchSettings());
          } catch {
            /* keep the optimistic value; the error is already surfaced */
          }
        }
      });
  }, []);

  return (
    <section className="ws">
      <header className="ws__head">
        <div>
          <h2 className="ws__title">Settings</h2>
          <p className="ws__sub">
            Tune retrieval and agent behaviour. Changes apply to the next question and persist
            across restarts.
          </p>
        </div>
        {savedAt > 0 && !error && <span className="set__saved" key={savedAt}>Saved</span>}
      </header>

      <div className="ws__body">
        {error && <p className="ev__error">{error}</p>}
        {!settings && !error && <div className="empty"><p className="empty__text">Loading settings…</p></div>}

        {settings && (
          <>
            {GROUPS.map((group) => (
            <div className="set__group" key={group.title}>
              <div className="set__group-head">
                <span className="set__group-title">{group.title}</span>
                <span className="set__group-note">{group.note}</span>
              </div>
              {group.rows.map((row) => (
                <div className="set__row" key={row.key}>
                  <div className="set__row-text">
                    <div className="set__row-label">
                      {row.label}
                      <InfoTip help={row.help} label={row.label} />
                    </div>
                    <div className="set__row-hint">{row.hint}</div>
                  </div>
                  <div className="set__row-control">
                    {row.kind === "toggle" && (
                      <label className="switch">
                        <input
                          type="checkbox"
                          checked={settings[row.key]}
                          onChange={(e) => void apply({ [row.key]: e.target.checked } as Partial<AppSettings>)}
                        />
                        <span className="switch__track"><span className="switch__knob" /></span>
                      </label>
                    )}
                    {row.kind === "slider" && (
                      <div className="set__slider">
                        <input
                          type="range"
                          min={row.min}
                          max={row.max}
                          step={row.step}
                          value={settings[row.key]}
                          onChange={(e) => void apply({ [row.key]: Number(e.target.value) } as Partial<AppSettings>)}
                        />
                        <span className="set__slider-val">{settings[row.key].toFixed(2)}</span>
                      </div>
                    )}
                    {row.kind === "number" && (
                      <NumberField
                        value={settings[row.key]}
                        min={row.min}
                        max={row.max}
                        step={row.step}
                        onCommit={(v) => void apply({ [row.key]: v } as Partial<AppSettings>)}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}

/**
 * A small "i" affordance that reveals a plain-language explanation on hover or
 * keyboard focus — what the setting does and what changing it actually affects.
 * CSS drives visibility (`:hover` / `:focus-within`); the button is focusable so
 * keyboard and screen-reader users get the same help.
 */
const TIP_WIDTH = 290;

function InfoTip({ help, label }: { help: Help; label: string }) {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // Position a fixed, body-portaled tooltip from the icon's screen rect, clamped
  // to the viewport so it's never clipped by the scroll container or run off-edge.
  const show = () => {
    const rect = btnRef.current?.getBoundingClientRect();
    if (!rect) return;
    const margin = 12;
    const estHeight = 130; // short, 3-line tooltip; enough to decide above/below
    const left = Math.min(Math.max(margin, rect.left), window.innerWidth - TIP_WIDTH - margin);
    const below = rect.bottom + 8;
    const top = below + estHeight > window.innerHeight - margin ? rect.top - estHeight : below;
    setPos({ top, left });
  };

  return (
    <span className="set__info" onMouseEnter={show} onMouseLeave={() => setPos(null)}>
      <button
        ref={btnRef}
        type="button"
        className="set__info-btn"
        aria-label={`What does “${label}” do?`}
        onFocus={show}
        onBlur={() => setPos(null)}
      >
        <svg
          className="set__info-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5" />
          <path d="M12 7.6h.01" />
        </svg>
      </button>
      {pos &&
        createPortal(
          <span className="set__tip" role="tooltip" style={{ top: pos.top, left: pos.left }}>
            <span className="set__tip-what">{help.what}</span>
            <span className="set__tip-effect">{help.effects[0]}</span>
            <span className="set__tip-effect">{help.effects[1]}</span>
          </span>,
          document.body,
        )}
    </span>
  );
}

/**
 * A bounded number input that keeps a local draft while typing (so clearing the
 * field to retype never sticks) and commits a clamped value on blur or Enter.
 */
function NumberField({
  value,
  min,
  max,
  step,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  const commit = () => {
    const parsed = Number(draft);
    let next = Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : value;
    if (Number.isInteger(step)) next = Math.round(next); // int knobs reject fractions
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };

  return (
    <input
      className="set__number"
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}
