/**
 * Typed HTTP client for the Lore sidecar.
 *
 * The base URL comes from the `VITE_SIDECAR_URL` env var (see `.env.example`),
 * with a loopback fallback so the app works out of the box in development.
 */

const DEFAULT_SIDECAR_URL = "http://127.0.0.1:8765";

/** Resolved base URL of the sidecar, without a trailing slash. */
export const sidecarBaseUrl: string = (
  import.meta.env.VITE_SIDECAR_URL ?? DEFAULT_SIDECAR_URL
).replace(/\/$/, "");

/** Readiness of each embedded data store. */
export interface DatabasesHealth {
  sqlite: boolean;
  lancedb: boolean;
}

/** Status of the local Ollama runtime. */
export interface OllamaHealth {
  reachable: boolean;
  installed_models: string[];
  missing_models: string[];
  error?: string | null;
}

/** Response shape of the sidecar `/health` endpoint. */
export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  databases: DatabasesHealth;
  ollama: OllamaHealth;
}

/**
 * Fetch the sidecar health status.
 *
 * @param signal optional AbortSignal to cancel the request (e.g. on unmount).
 * @throws if the request fails or returns a non-2xx status.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${sidecarBaseUrl}/health`, { signal });
  if (!response.ok) {
    throw new Error(`Sidecar health check failed (HTTP ${response.status})`);
  }
  return (await response.json()) as HealthResponse;
}

/** Live status of a code-index ingestion run (mirrors the sidecar IndexJob). */
export interface IndexJob {
  state: "idle" | "running" | "done" | "error";
  repo: string | null;
  total: number;
  processed: number;
  errors: string[];
  message: string | null;
}

/** Aggregate index counts. */
export interface IndexStats {
  code_chunks: number;
  commits: number;
  doc_chunks: number;
}

async function parseOrThrow<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // response had no JSON body; keep the status-based detail.
    }
    throw new Error(`${action} failed: ${detail}`);
  }
  return (await response.json()) as T;
}

/** Start indexing the repository at the given path. */
export async function startCodeIndex(path: string, force = false): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, force }),
  });
  return parseOrThrow<IndexJob>(response, "Start indexing");
}

/** Fetch the current/last indexing job status. */
export async function fetchIndexStatus(signal?: AbortSignal): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/status`, { signal });
  return parseOrThrow<IndexJob>(response, "Fetch index status");
}

/** Fetch aggregate index counts. */
export async function fetchIndexStats(signal?: AbortSignal): Promise<IndexStats> {
  const response = await fetch(`${sidecarBaseUrl}/index/stats`, { signal });
  return parseOrThrow<IndexStats>(response, "Fetch index stats");
}

/** Start indexing the repository's git history (reuses the IndexJob shape). */
export async function startHistoryIndex(path: string, force = false): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/history`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, force }),
  });
  return parseOrThrow<IndexJob>(response, "Start history indexing");
}

/** Fetch the current/last history-indexing job status. */
export async function fetchHistoryStatus(signal?: AbortSignal): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/history/status`, { signal });
  return parseOrThrow<IndexJob>(response, "Fetch history status");
}

/** Start indexing the repository's documentation (reuses the IndexJob shape). */
export async function startDocsIndex(path: string, force = false): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/docs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, force }),
  });
  return parseOrThrow<IndexJob>(response, "Start docs indexing");
}

/** Fetch the current/last docs-indexing job status. */
export async function fetchDocsStatus(signal?: AbortSignal): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/docs/status`, { signal });
  return parseOrThrow<IndexJob>(response, "Fetch docs status");
}

/** A retrieved code chunk cited as a source for an answer. */
export interface Source {
  chunk_id: string;
  repo: string;
  file_path: string;
  language: string;
  kind: string;
  symbol: string;
  qualified_name: string;
  start_line: number;
  end_line: number;
  code: string;
  score: number;
}

/** A git commit cited as a source for a historical answer. */
export interface CommitHit {
  sha: string;
  author: string;
  committed_at: string;
  message: string;
  summary: string;
  files: string;
  score: number;
}

/** A documentation chunk cited as a source for an answer. */
export interface DocHit {
  chunk_id: string;
  repo: string;
  file_path: string;
  heading: string;
  start_line: number;
  end_line: number;
  text: string;
  score: number;
}

/** A grounded answer with its sources (mirrors the sidecar AnswerResponse). */
export interface AnswerResponse {
  answer: string;
  sources: Source[];
  grounded: boolean;
  unsupported: string[];
  categories: string[]; // the router's classification of the question
  graph_used: boolean; // whether graph context was folded in
  corrected: boolean; // whether a self-correction retry produced this answer
  commits: CommitHit[]; // git-history commits cited in the answer
  docs: DocHit[]; // documentation chunks cited in the answer
}

/** One prior exchange, sent as context for follow-up questions. */
export interface ConversationTurn {
  question: string;
  answer: string;
}

/** Ask a grounded question about the indexed repository. */
export async function askQuestion(
  question: string,
  history: ConversationTurn[] = [],
  signal?: AbortSignal,
): Promise<AnswerResponse> {
  const response = await fetch(`${sidecarBaseUrl}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
    signal,
  });
  return parseOrThrow<AnswerResponse>(response, "Ask question");
}

// --- Streaming answers (NDJSON over /query/stream) ----------------------------

/** Early event carrying the query classification and the retrieved sources. */
export interface MetaEvent {
  categories: string[];
  graph_used: boolean;
  sources: Source[];
  commits: CommitHit[];
  docs: DocHit[];
}

/** Terminal event with the grounding outcome. */
export interface FinalEvent {
  grounded: boolean;
  unsupported: string[];
  corrected: boolean;
}

/** Callbacks invoked as the answer streams in. All are optional. */
export interface StreamHandlers {
  onMeta?: (event: MetaEvent) => void;
  onToken?: (text: string) => void;
  onStatus?: (stage: string) => void;
  onReplace?: () => void;
  onFinal?: (event: FinalEvent) => void;
  onError?: (detail: string) => void;
}

type StreamEvent =
  | ({ type: "meta" } & MetaEvent)
  | { type: "token"; text: string }
  | { type: "status"; stage: string }
  | { type: "replace" }
  | ({ type: "final" } & FinalEvent)
  | { type: "error"; detail: string };

function dispatchStreamEvent(event: StreamEvent, handlers: StreamHandlers): void {
  switch (event.type) {
    case "meta":
      handlers.onMeta?.(event);
      break;
    case "token":
      handlers.onToken?.(event.text);
      break;
    case "status":
      handlers.onStatus?.(event.stage);
      break;
    case "replace":
      handlers.onReplace?.();
      break;
    case "final":
      handlers.onFinal?.(event);
      break;
    case "error":
      handlers.onError?.(event.detail);
      break;
  }
}

/**
 * Ask a question and stream the answer as it is generated.
 *
 * Reads the NDJSON event stream from `/query/stream` and dispatches each event
 * to the provided handlers. Resolves when the stream ends; rejects on a network
 * error (an aborted request surfaces as an `AbortError`).
 */
export async function askQuestionStream(
  question: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  history: ConversationTurn[] = [],
): Promise<void> {
  const response = await fetch(`${sidecarBaseUrl}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Ask question failed: HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushLine = (line: string) => {
    const trimmed = line.trim();
    if (trimmed) dispatchStreamEvent(JSON.parse(trimmed) as StreamEvent, handlers);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      flushLine(buffer.slice(0, newline));
      buffer = buffer.slice(newline + 1);
    }
  }
  flushLine(buffer); // any trailing line without a newline
}

/** A node in the dependency graph. */
export interface GraphNode {
  id: string;
  label: string;
  file_path: string;
  in_degree: number;
  out_degree: number;
  in_cycle: boolean;
}

/** A directed dependency edge (source imports target). */
export interface GraphLink {
  source: string;
  target: string;
}

/** The dependency graph visualization payload. */
export interface GraphViz {
  nodes: GraphNode[];
  links: GraphLink[];
  truncated: boolean;
}

/** Which graph layer to view: exact imports, or LLM-extracted relationships. */
export type GraphLayer = "static" | "semantic";

/** Fetch a graph layer for visualization. */
export async function fetchGraph(
  layer: GraphLayer = "static",
  signal?: AbortSignal,
): Promise<GraphViz> {
  const response = await fetch(`${sidecarBaseUrl}/graph?layer=${layer}`, { signal });
  return parseOrThrow<GraphViz>(response, "Fetch graph");
}

/** Per-question evaluation result. */
export interface EvalQuestionResult {
  question: string;
  grounded: boolean;
  recall_hit: boolean | null; // null when the question has no labelled files
  relevancy: number;
}

/** Aggregate evaluation report. */
export interface EvalReport {
  total: number;
  faithfulness: number;
  answer_relevancy: number;
  recall_at_k: number | null; // null when no question is labelled
  per_question: EvalQuestionResult[];
}

/** Live status of an evaluation run (mirrors the sidecar EvalJob). */
export interface EvalJob {
  state: "idle" | "running" | "done" | "error";
  repo: string | null;
  total: number;
  processed: number;
  configured: boolean; // whether a .lore/eval.yml was found
  message: string | null;
  report: EvalReport | null;
}

/** Start an evaluation run against the indexed repo's `.lore/eval.yml`. */
export async function runEval(): Promise<EvalJob> {
  const response = await fetch(`${sidecarBaseUrl}/eval/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return parseOrThrow<EvalJob>(response, "Run evaluation");
}

/** Fetch the current/last evaluation status (and report, when done). */
export async function fetchEvalStatus(signal?: AbortSignal): Promise<EvalJob> {
  const response = await fetch(`${sidecarBaseUrl}/eval/status`, { signal });
  return parseOrThrow<EvalJob>(response, "Fetch eval status");
}

/** An architecture rule violation (a forbidden dependency edge). */
export interface Violation {
  rule: string;
  severity: string;
  src_file: string;
  dst_file: string;
  from_layer: string;
  to_layer: string;
}

/** Result of evaluating a repo's architecture rules. */
export interface ViolationsResponse {
  configured: boolean;
  violations: Violation[];
}

/** Fetch architecture-rule violations for the indexed repo. */
export async function fetchViolations(signal?: AbortSignal): Promise<ViolationsResponse> {
  const response = await fetch(`${sidecarBaseUrl}/graph/violations`, { signal });
  return parseOrThrow<ViolationsResponse>(response, "Fetch violations");
}

/** A window of a cited file's lines (mirrors the sidecar SourceView). */
export interface SourceView {
  repo: string;
  file_path: string;
  start_line: number;
  end_line: number;
  window_start: number;
  lines: string[];
}

// --- Model pull (NDJSON over /models/pull) ------------------------------------

/** A download-progress update while pulling a model. */
export interface PullProgress {
  status: string;
  completed: number | null;
  total: number | null;
}

/** Callbacks invoked as a model pull streams. All are optional. */
export interface PullHandlers {
  onProgress?: (event: PullProgress) => void;
  onDone?: () => void;
  onError?: (detail: string) => void;
}

type PullEvent =
  | ({ type: "progress" } & PullProgress)
  | { type: "done" }
  | { type: "error"; detail: string };

/** Pull an Ollama model, dispatching progress events as they stream in. */
export async function pullModelStream(
  model: string,
  handlers: PullHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${sidecarBaseUrl}/models/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Pull failed: HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const event = JSON.parse(trimmed) as PullEvent;
    if (event.type === "progress") handlers.onProgress?.(event);
    else if (event.type === "done") handlers.onDone?.();
    else if (event.type === "error") handlers.onError?.(event.detail);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      flushLine(buffer.slice(0, newline));
      buffer = buffer.slice(newline + 1);
    }
  }
  flushLine(buffer);
}

// --- Refactoring agent --------------------------------------------------------

/** A structural problem worth refactoring (mirrors the sidecar RefactorCandidate). */
export interface RefactorCandidate {
  id: string;
  kind: "cycle" | "hub" | "violation";
  severity: "high" | "medium" | "low";
  title: string;
  summary: string;
  files: string[];
  symbols: string[];
}

/** The detected refactor candidates for a repo. */
export interface RefactorResponse {
  repo: string | null;
  candidates: RefactorCandidate[];
}

/** Fetch the refactoring candidates for the indexed repo. */
export async function fetchRefactor(signal?: AbortSignal): Promise<RefactorResponse> {
  const response = await fetch(`${sidecarBaseUrl}/refactor`, { signal });
  return parseOrThrow<RefactorResponse>(response, "Fetch refactor candidates");
}

/** Request a grounded LLM refactor proposal for one candidate. */
export async function suggestRefactor(
  candidate: RefactorCandidate,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(`${sidecarBaseUrl}/refactor/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(candidate),
    signal,
  });
  const body = await parseOrThrow<{ proposal: string }>(response, "Suggest refactor");
  return body.proposal;
}

// --- Settings (live-editable retrieval/agent knobs) ---------------------------

/** The UI-exposed subset of sidecar settings (mirrors the sidecar SettingsView). */
export interface AppSettings {
  rerank_enabled: boolean;
  mmr_enabled: boolean;
  mmr_lambda: number;
  parent_expansion_enabled: boolean;
  query_expansion_enabled: boolean;
  query_expansion_n: number;
  self_correct_enabled: boolean;
  iterative_enabled: boolean;
  iterative_max_rounds: number;
  grounding_enabled: boolean;
  router_enabled: boolean;
  graphrag_enabled: boolean;
  conversation_enabled: boolean;
  retrieval_top_k: number;
}

/** Fetch the current effective settings. */
export async function fetchSettings(signal?: AbortSignal): Promise<AppSettings> {
  const response = await fetch(`${sidecarBaseUrl}/settings`, { signal });
  return parseOrThrow<AppSettings>(response, "Fetch settings");
}

/** Patch one or more settings; returns the new effective settings. */
export async function updateSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  const response = await fetch(`${sidecarBaseUrl}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseOrThrow<AppSettings>(response, "Update settings");
}

/** Fetch the lines around a cited range, for the in-app source viewer. */
export async function fetchSource(
  repo: string,
  path: string,
  start: number,
  end: number,
  signal?: AbortSignal,
): Promise<SourceView> {
  const params = new URLSearchParams({
    repo,
    path,
    start: String(start),
    end: String(end),
  });
  const response = await fetch(`${sidecarBaseUrl}/source?${params}`, { signal });
  return parseOrThrow<SourceView>(response, "Fetch source");
}
