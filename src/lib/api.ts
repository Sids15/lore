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
export async function startCodeIndex(path: string): Promise<IndexJob> {
  const response = await fetch(`${sidecarBaseUrl}/index/code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
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

/** A grounded answer with its sources (mirrors the sidecar AnswerResponse). */
export interface AnswerResponse {
  answer: string;
  sources: Source[];
  grounded: boolean;
  unsupported: string[];
}

/** Ask a grounded question about the indexed repository. */
export async function askQuestion(
  question: string,
  signal?: AbortSignal,
): Promise<AnswerResponse> {
  const response = await fetch(`${sidecarBaseUrl}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  return parseOrThrow<AnswerResponse>(response, "Ask question");
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
