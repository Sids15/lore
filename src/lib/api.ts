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

/** Response shape of the sidecar `/health` endpoint. */
export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  databases: DatabasesHealth;
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
