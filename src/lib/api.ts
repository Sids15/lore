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
