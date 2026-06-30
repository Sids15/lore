import { useCallback, useEffect, useRef, useState } from "react";

import { fetchSettings, updateSettings, type AppSettings } from "../lib/api";

/** A group of related settings rendered as a card. */
interface Group {
  title: string;
  note: string;
  rows: Row[];
}

type Row =
  | { kind: "toggle"; key: BoolKey; label: string; hint: string }
  | { kind: "number"; key: NumKey; label: string; hint: string; min: number; max: number; step: number }
  | { kind: "slider"; key: NumKey; label: string; hint: string; min: number; max: number; step: number };

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
      { kind: "toggle", key: "rerank_enabled", label: "Cross-encoder rerank", hint: "Re-score hybrid candidates for sharper relevance." },
      { kind: "toggle", key: "mmr_enabled", label: "MMR diversity", hint: "Drop near-duplicate chunks from the final selection." },
      { kind: "slider", key: "mmr_lambda", label: "MMR λ", hint: "1.0 = pure relevance, 0.0 = pure diversity.", min: 0, max: 1, step: 0.05 },
      { kind: "toggle", key: "parent_expansion_enabled", label: "Parent-chunk expansion", hint: "Attach a method's class header + file imports as context." },
      { kind: "toggle", key: "query_expansion_enabled", label: "Query expansion", hint: "RRF-fuse alternate phrasings on the first pass (opt-in)." },
      { kind: "number", key: "query_expansion_n", label: "Expansion phrasings", hint: "How many alternate phrasings to retrieve.", min: 1, max: 8, step: 1 },
      { kind: "number", key: "retrieval_top_k", label: "Results per query (k)", hint: "Chunks kept after reranking.", min: 1, max: 30, step: 1 },
    ],
  },
  {
    title: "Agent",
    note: "Routing, graph context, grounding, and self-correction behaviour.",
    rows: [
      { kind: "toggle", key: "router_enabled", label: "Question router", hint: "Classify each question to route retrieval." },
      { kind: "toggle", key: "graphrag_enabled", label: "GraphRAG context", hint: "Fold dependency/semantic-graph facts into answers." },
      { kind: "toggle", key: "grounding_enabled", label: "Grounding check", hint: "Second pass that verifies the answer against sources." },
      { kind: "toggle", key: "self_correct_enabled", label: "Self-correction", hint: "Re-retrieve and retry when an answer is ungrounded." },
      { kind: "toggle", key: "iterative_enabled", label: "Iterative loop", hint: "Allow multiple correction rounds, not just one (opt-in)." },
      { kind: "number", key: "iterative_max_rounds", label: "Max rounds", hint: "Total passes incl. the first (iterative loop).", min: 2, max: 6, step: 1 },
    ],
  },
  {
    title: "Conversation",
    note: "Multi-turn follow-up handling.",
    rows: [
      { kind: "toggle", key: "conversation_enabled", label: "Multi-turn", hint: "Condense follow-ups into standalone questions." },
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

        {settings &&
          GROUPS.map((group) => (
            <div className="set__group" key={group.title}>
              <div className="set__group-head">
                <span className="set__group-title">{group.title}</span>
                <span className="set__group-note">{group.note}</span>
              </div>
              {group.rows.map((row) => (
                <div className="set__row" key={row.key}>
                  <div className="set__row-text">
                    <div className="set__row-label">{row.label}</div>
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
      </div>
    </section>
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
